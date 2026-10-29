"""Offline checks for the fixed taxonomy and explicit Drive-ID assignments."""

from copy import deepcopy

import pytest
import yaml

from doctree.content_taxonomy.category_classifier import (
    ClassificationError,
    classify_records,
    load_catalog,
)


@pytest.fixture
def documents():
    return (
        {
            "schema_version": 1,
            "categories": [
                {
                    "id": "cs",
                    "name": "컴퓨터 과학 기초",
                    "subcategories": [
                        {"id": "cs.algorithms", "name": "알고리즘·자료구조"},
                        {"id": "cs.os", "name": "운영체제"},
                    ],
                },
                {
                    "id": "programming",
                    "name": "프로그래밍",
                    "subcategories": [{"id": "programming.python", "name": "Python"}],
                },
            ],
        },
        {
            "schema_version": 1,
            "contents": [
                {"file_id": "drive-known", "title": "원래 콘텐츠 제목", "category_id": "cs.algorithms"}
            ],
        },
    )


@pytest.fixture
def load_documents(tmp_path):
    def load(categories, contents):
        category_tree_path = tmp_path / "category_tree.yaml"
        content_map_path = tmp_path / "content_category_map.yaml"
        category_tree_path.write_text(yaml.safe_dump(categories, allow_unicode=True), encoding="utf-8")
        content_map_path.write_text(yaml.safe_dump(contents, allow_unicode=True), encoding="utf-8")
        return load_catalog(category_tree_path, content_map_path)

    return load


def test_fixed_taxonomy_preserves_order_and_empty_subcategories(documents, load_documents):
    catalog = load_documents(*documents)

    assert [category.id for category in catalog.categories] == ["cs", "programming"]
    assert [child.id for child in catalog.categories[0].subcategories] == ["cs.algorithms", "cs.os"]
    assert catalog.categories[0].name == "컴퓨터 과학 기초"
    result = classify_records([], catalog, strict=True)
    assert result.catalog is catalog
    assert result.contents == ()
    assert result.catalog.categories[0].subcategories[1].id == "cs.os"


def test_moving_and_renaming_a_content_preserves_assignment(documents, load_documents):
    catalog = load_documents(*documents)
    record = {
        "id": "drive-known",
        "name": "완전히 다른 이름.pdf",
        "folder_path": "새 폴더",
        "size_bytes": 12345,
    }
    before = deepcopy(record)

    result = classify_records([record], catalog, strict=True)

    assert result.contents[0].category_id == "cs.algorithms"
    assert result.contents[0].record == before
    assert result.contents[0].record is not record
    assert record == before
    assert result.unclassified == ()


def test_unknown_id_never_inherits_category_from_title_or_folder(documents, load_documents):
    catalog = load_documents(*documents)
    result = classify_records(
        [{"id": "new-drive-id", "name": "원래 콘텐츠 제목", "folder_path": "컴퓨터 과학 기초/알고리즘·자료구조"}],
        catalog,
    )

    assert result.contents[0].category_id is None
    assert result.unclassified == result.contents
    assert [category.id for category in result.catalog.categories] == ["cs", "programming"]


def test_strict_mode_reports_every_unclassified_id(documents, load_documents):
    catalog = load_documents(*documents)
    records = [
        {"id": "drive-known", "name": "Known.pdf"},
        {"id": "new-one", "name": "New.pdf"},
        {"id": "new-two", "name": "New.pdf"},
    ]

    with pytest.raises(ClassificationError) as error:
        classify_records(records, catalog, strict=True)

    assert "new-one" in str(error.value)
    assert "new-two" in str(error.value)
    assert "drive-known" not in str(error.value)


def test_duplicate_assignments_are_rejected_even_when_identical(documents, load_documents):
    categories, contents = documents
    contents["contents"].append(dict(contents["contents"][0]))

    with pytest.raises(ClassificationError, match="drive-known"):
        load_documents(categories, contents)


@pytest.mark.parametrize("category_id", ["cs", "cs.not_registered"])
def test_assignment_requires_an_existing_leaf(category_id, documents, load_documents):
    categories, contents = documents
    contents["contents"][0]["category_id"] = category_id

    with pytest.raises(ClassificationError, match="세부분야"):
        load_documents(categories, contents)


def test_global_node_ids_cannot_be_reused_by_a_parent(documents, load_documents):
    categories, contents = documents
    categories["categories"][1]["id"] = "cs.algorithms"

    with pytest.raises(ClassificationError, match="중복"):
        load_documents(categories, contents)


def test_global_node_ids_cannot_be_reused_in_another_branch(documents, load_documents):
    categories, contents = documents
    categories["categories"][1]["subcategories"][0]["id"] = "cs.os"

    with pytest.raises(ClassificationError, match="중복"):
        load_documents(categories, contents)


@pytest.mark.parametrize("level", ["parent", "leaf"])
def test_sibling_names_must_be_unique(level, documents, load_documents):
    categories, contents = documents
    nodes = categories["categories"] if level == "parent" else categories["categories"][0]["subcategories"]
    nodes[1]["name"] = nodes[0]["name"]

    with pytest.raises(ClassificationError, match="중복"):
        load_documents(categories, contents)


def test_equal_names_are_allowed_in_different_branches(documents, load_documents):
    categories, contents = documents
    categories["categories"][1]["subcategories"][0]["name"] = "운영체제"

    assert load_documents(categories, contents).categories[1].subcategories[0].name == "운영체제"


@pytest.mark.parametrize("document_index", [0, 1])
@pytest.mark.parametrize("version", [True, "1", 1.0, 2, None])
def test_schema_version_is_exactly_integer_one(document_index, version, documents, load_documents):
    documents[document_index]["schema_version"] = version

    with pytest.raises(ClassificationError, match="schema_version"):
        load_documents(*documents)


@pytest.mark.parametrize(
    "location, field, value",
    [
        ("root", "categories", []),
        ("root", "categories", {}),
        ("category", "subcategories", []),
        ("category", "subcategories", "cs.algorithms"),
        ("category", "name", " "),
        ("category", "id", "컴퓨터"),
        ("category", "id", "CS"),
        ("category", "id", "cs..invalid"),
        ("subcategory", "id", 12),
        ("subcategory", "name", False),
        ("content", "file_id", ""),
        ("content", "title", None),
        ("content", "category_id", ["cs.algorithms"]),
    ],
)
def test_invalid_schema_values_are_rejected(location, field, value, documents, load_documents):
    categories, contents = documents
    targets = {
        "root": categories,
        "category": categories["categories"][0],
        "subcategory": categories["categories"][0]["subcategories"][0],
        "content": contents["contents"][0],
    }
    targets[location][field] = value

    with pytest.raises(ClassificationError):
        load_documents(categories, contents)


@pytest.mark.parametrize("location", ["categories_root", "contents_root", "category", "subcategory", "content"])
@pytest.mark.parametrize("change", ["extra", "missing"])
def test_unknown_and_missing_fields_fail_validation(location, change, documents, load_documents):
    categories, contents = documents
    targets = {
        "categories_root": categories,
        "contents_root": contents,
        "category": categories["categories"][0],
        "subcategory": categories["categories"][0]["subcategories"][0],
        "content": contents["contents"][0],
    }
    target = targets[location]
    if change == "extra":
        target["typo"] = "must not be ignored"
    else:
        del target[next(iter(target))]

    with pytest.raises(ClassificationError):
        load_documents(categories, contents)


def test_empty_content_assignments_are_valid(documents, load_documents):
    categories, contents = documents
    contents["contents"] = []

    assert load_documents(categories, contents).assignments == ()


@pytest.mark.parametrize("duplicate", ["version", "nested"])
def test_duplicate_yaml_keys_do_not_silently_overwrite(tmp_path, duplicate):
    category_tree_path = tmp_path / "category_tree.yaml"
    content_map_path = tmp_path / "content_category_map.yaml"
    categories_text = """schema_version: 1
categories:
  - id: cs
    name: CS
    subcategories:
      - id: cs.algorithms
        name: Algorithms
"""
    if duplicate == "version":
        categories_text += "schema_version: 1\n"
    else:
        categories_text += "        name: Silently replaced name\n"
    category_tree_path.write_text(categories_text, encoding="utf-8")
    content_map_path.write_text("schema_version: 1\ncontents: []\n", encoding="utf-8")

    with pytest.raises(ClassificationError, match="중복 키"):
        load_catalog(category_tree_path, content_map_path)


@pytest.mark.parametrize("text", ["[broken", "!!python/object:os.system {}", "null", "[]"])
def test_malformed_or_unsafe_yaml_fails_cleanly(tmp_path, text):
    category_tree_path = tmp_path / "category_tree.yaml"
    content_map_path = tmp_path / "content_category_map.yaml"
    category_tree_path.write_text(text, encoding="utf-8")
    content_map_path.write_text("schema_version: 1\ncontents: []\n", encoding="utf-8")

    with pytest.raises(ClassificationError):
        load_catalog(category_tree_path, content_map_path)


def test_missing_configuration_file_fails_cleanly(tmp_path):
    with pytest.raises(ClassificationError, match=r"category_tree\.yaml"):
        load_catalog(tmp_path / "category_tree.yaml", tmp_path / "content_category_map.yaml")


@pytest.mark.parametrize(
    "records",
    [
        [{"id": "drive-known", "name": "A.pdf"}, {"id": "drive-known", "name": "B.pdf"}],
        [{"id": "new-id", "name": "A.pdf"}, {"id": "new-id", "name": "A.pdf"}],
    ],
)
def test_duplicate_snapshot_ids_are_rejected(records, documents, load_documents):
    with pytest.raises(ClassificationError, match="중복 파일 ID"):
        classify_records(records, load_documents(*documents))


@pytest.mark.parametrize(
    "record",
    [None, [], {}, {"id": 123, "name": "A.pdf"}, {"id": "  ", "name": "A.pdf"}, {"id": "file", "name": ""}],
)
def test_snapshot_records_require_nonempty_string_id_and_name(record, documents, load_documents):
    with pytest.raises(ClassificationError):
        classify_records([record], load_documents(*documents))


def test_unhashable_yaml_mapping_key_is_rejected_with_clear_error(tmp_path):
    category_tree_path = tmp_path / "category_tree.yaml"
    content_map_path = tmp_path / "content_category_map.yaml"
    category_tree_path.write_text("? [unhashable, list, key]\n: value\n", encoding="utf-8")
    content_map_path.write_text("schema_version: 1\ncontents: []\n", encoding="utf-8")

    with pytest.raises(ClassificationError, match="YAML 매핑 키는 단일 값이어야 합니다"):
        load_catalog(category_tree_path, content_map_path)


def test_classify_records_defensively_copies_input_record_Against_caller_mutation(documents, load_documents):
    catalog = load_documents(*documents)
    caller_record = {"id": "drive-known", "name": "Original.pdf", "folder_path": "CS"}
    result = classify_records([caller_record], catalog)

    # 호출 측이 원본 dict를 사후 변경(mutate)하더라도 분류 결과 내부의 레코드는 오염되지 않는다.
    caller_record["name"] = "Mutated.pdf"
    assert result.contents[0].record["name"] == "Original.pdf"
