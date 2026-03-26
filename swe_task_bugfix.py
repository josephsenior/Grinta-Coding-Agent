def first_n_evens(n):
    """Return the first n even numbers starting from 0."""
    result = []
    for i in range(n + 1):  # BUG: should be range(n)
        if i % 2 == 0:
            result.append(i)
    return result
