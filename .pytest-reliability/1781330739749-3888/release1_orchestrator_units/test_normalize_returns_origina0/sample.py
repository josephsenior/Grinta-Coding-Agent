def greet(name):
    return f"Hello, {name}!"


def add(a, b):
    return a + b


class Calculator:
    def multiply(self, x, y):
        return x * y

    def divide(self, x, y):
        if y == 0:
            raise ValueError("Division by zero")
        return x / y
