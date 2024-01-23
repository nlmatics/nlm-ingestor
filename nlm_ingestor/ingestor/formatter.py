# formatting done while cleaning
def connect(prev, curr):
    has_space = prev.endswith(" ")
    has_hyphen = prev.endswith("-")
    if has_hyphen:
        result = prev[0:-1] + curr
        return result
    result = prev + ("" if has_space else " ") + curr
    return result


def fix_mixedcase_words(word):
    # if lower no uppers after
    # if upper no
    if len(word) < 1 or word.isupper() or word.islower():
        return word
    else:
        # check the first two letters to see if it is just a titled word e.g. Hello
        if word[0].isupper() and word[1].islower():
            return word.capitalize()
        else:
            # e.g. return HELLO if HEllo else return hello if heLlo
            return word.lower() if word[0].islower() else word.upper()


# formatting done after cleaning
