from .core import process_payment


def main():
    result = process_payment(1.0, "USD")
    print(result)


if __name__ == "__main__":
    main()
