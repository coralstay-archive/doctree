import asyncio
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    AsyncOpenAI = None
    OPENAI_AVAILABLE = False


class LLMSummarizer:
    """마크다운 구조 분석, 목차/앵커 생성, LLM(OpenAI/Ollama/로컬 LLM) 비동기 요약 및 최종 결합"""

    def __init__(self, md_path: str or Path, api_key: Optional[str] = None, model: Optional[str] = None, base_url: Optional[str] = None):
        self.md_path = Path(md_path)
        self.content = self.md_path.read_text(encoding="utf-8", errors="replace") if self.md_path.exists() else ""
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL", None)
        
        self.client = None
        if OPENAI_AVAILABLE:
            # API 키가 있거나 로컬 LLM(Ollama / vLLM / LocalAI 등 base_url 지정)인 경우 클라이언트 생성
            effective_key = self.api_key or ("dummy-key" if self.base_url else "")
            if effective_key:
                self.client = AsyncOpenAI(api_key=effective_key, base_url=self.base_url)

    def generate_index(self) -> str:
        """마크다운 #, ## 헤더를 파싱하여 TOC 목차 및 앵커 링크 생성"""
        lines = self.content.splitlines()
        index_entries: List[str] = []

        for line in lines:
            match = re.match(r'^(#{1,3})\s+(.+)$', line.strip())
            if match:
                hashes, title = match.groups()
                level = len(hashes)
                indent = "  " * (level - 1)
                # GitHub 스타일 앵커 태그 생성
                anchor = re.sub(r'[^\w\s-]', '', title.lower()).strip().replace(' ', '-')
                index_entries.append(f"{indent}- [{title}](#{anchor})")

        if not index_entries:
            return "## 목차\n- 목차가 존재하지 않습니다.\n"

        return "## 목차\n" + "\n".join(index_entries) + "\n"

    def split_into_chapters(self) -> List[Dict[str, str]]:
        """헤더(# 또는 ##)를 기준으로 문서를 챕터 단위로 분할"""
        lines = self.content.splitlines()
        chapters = []
        current_title = "Intro"
        current_body = []

        for line in lines:
            header_match = re.match(r'^(#{1,2})\s+(.+)$', line.strip())
            if header_match:
                if current_body:
                    chapters.append({
                        "title": current_title,
                        "content": "\n".join(current_body).strip()
                    })
                    current_body = []
                current_title = header_match.group(2).strip()
            current_body.append(line)

        if current_body:
            chapters.append({
                "title": current_title,
                "content": "\n".join(current_body).strip()
            })

        return chapters

    async def _summarize_single_chapter(self, title: str, text: str) -> Dict[str, str]:
        """단일 챕터에 대한 비동기 LLM 요약 요청"""
        if not self.client or not text.strip():
            # LLM API 미연동 시 기본 발췌 요약
            preview = text.strip()[:200] + ("..." if len(text.strip()) > 200 else "")
            return {"title": title, "summary": f"{preview}"}

        # 텍스트가 너무 긴 경우 적절히 잘라내어 요청
        truncated_text = text[:8000]
        prompt = (
            f"다음은 도서의 '{title}' 섹션 본문입니다.\n"
            f"핵심 내용을 3~5개 불릿 포인트로 한국어로 명확하고 간결하게 요약해 주세요.\n\n"
            f"본문:\n{truncated_text}"
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "도서 요약 및 마크다운 정리 전문가입니다."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500
            )
            summary = response.choices[0].message.content.strip()
            return {"title": title, "summary": summary}
        except Exception as e:
            print(f"[LLMSummarizer] 챕터 '{title}' 요약 중 에러: {e}")
            return {"title": title, "summary": f"[요약 생성 실패: {e}]"}

    async def _generate_all_summaries_async(self) -> List[Dict[str, str]]:
        chapters = self.split_into_chapters()
        tasks = [self._summarize_single_chapter(c["title"], c["content"]) for c in chapters]
        return await asyncio.gather(*tasks)

    def generate_chapter_summaries(self) -> str:
        """전체 챕터에 대해 비동기 병렬 요약을 실행하고 포맷팅된 문자열 반환"""
        summaries = asyncio.run(self._generate_all_summaries_async())
        
        md_summary = ["## AI 챕터별 핵심 요약\n"]
        for s in summaries:
            md_summary.append(f"### {s['title']}")
            md_summary.append(s['summary'] + "\n")

        return "\n".join(md_summary)

    def save_final_markdown(
        self,
        metadata: Dict,
        index_content: str,
        summary_content: str,
        target_dir: str or Path
    ) -> Path:
        """YAML 프론트매터 + AI 요약 + 목차 + 변환된 본문을 결합하여 최종 파일 저장"""
        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)
        final_file = target_path / self.md_path.name

        # YAML 프론트매터 생성
        if YAML_AVAILABLE:
            frontmatter_str = yaml.dump(metadata, allow_unicode=True, sort_keys=False)
        else:
            frontmatter_lines = [f"{k}: {v}" for k, v in metadata.items()]
            frontmatter_str = "\n".join(frontmatter_lines) + "\n"
        
        full_content = (
            f"---\n{frontmatter_str}---\n\n"
            f"{summary_content}\n\n"
            f"{index_content}\n\n"
            f"## 본문\n\n"
            f"{self.content}"
        )

        final_file.write_text(full_content, encoding="utf-8")
        print(f"[LLMSummarizer] 최종 마크다운 파일 저장 완료: {final_file}")
        return final_file
