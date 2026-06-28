"""Tiny program used by the debugger walkthrough in examples/README.md."""


def parse_age(value: str) -> int:
    age = int(value)
    if age < 0:
        raise ValueError(f'negative age not allowed: {age}')
    return age


if __name__ == '__main__':
    parse_age('-5')
