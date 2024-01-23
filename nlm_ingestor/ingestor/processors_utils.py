import re

from . import patterns


# helper functions for processors
# Helper functions to help classify and clean text

# table functions
# works for numbers dilimted by spaces and commas
def space_delimited_numbers_check(line):
    space_del_numbers = False

    # finds any space delited numbers
    line = re.findall(patterns.space_d_numbers, line.replace(",", "").replace("$", ""))
    for cells in line:
        if len(re.findall(r"(\d)+", cells)) > 2:
            space_del_numbers = True
    # enures that there are at least 3 numbers seperated by a deliter
    return space_del_numbers


# general line functions
def incomplete_sentence(line):
    rule1 = False
    incomplete_words = [
        "&",
        "of",
        "the",
        "this",
        "a",
        "an",
        "to",
        "with",
        "or",
        "by",
        "these",
    ]
    if len(line) > 0:
        rule1 = line.replace(" ", "")[-1] in [",", "-", "/"]

    if line.split(" ")[-1] in incomplete_words:
        return True
    return rule1


# given string and list of strings, do a massive replace
def super_replace(phrase, src=[], trg=""):
    for i in src:
        phrase = phrase.replace(i, trg)
    return phrase


# find floating letters
def fix_spaced_letters(line):
    if len(re.findall(r"(\w\s+\w\s+\w)", line)):
        return "".join(line.split(" "))
    else:
        return line
