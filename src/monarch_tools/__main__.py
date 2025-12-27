import sys

def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if argv[:1] == ["hello"]:
        print("hello: monarch-tools is wired up")
        return 0

    print("usage: python -m monarch_tools hello")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
