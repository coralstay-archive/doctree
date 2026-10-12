import sys
from pathlib import Path

# 프로젝트 루트 경로 확보
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from main import cli_entry


def main():
    cli_entry()


if __name__ == "__main__":
    main()
