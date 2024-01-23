import os
import re
from math import log

import nlm_ingestor.ingestor as ingestor

word_file = os.path.join(
    os.path.dirname(os.path.abspath(ingestor.__file__)), "../ingestor_utils/words.txt",
)


class WordSplitter:
    def __init__(self, word_file=word_file):
        # Build a cost dictionary, assuming Zipf's law and cost = -math.log(probability).
        with open(word_file) as f:
            words = f.read().split()
            self._word2cost = {
                k: log((i + 1) * log(len(words))) for i, k in enumerate(words)
            }
            # add extra parameters
            self._word2cost["$"] = 1
            self._word2cost["%"] = 1
            self._word2cost[","] = 1
            self._word2cost["."] = 1
            self._word2cost["("] = 1
            self._word2cost[")"] = 1
            self._word2cost["/"] = 1
            self._word2cost["-"] = 1
            self._word2cost["'"] = 1
            self._word2cost["’"] = 1
            self._word2cost["’s"] = 1
            self._word2cost["'s"] = 1
            self._maxword = max(len(x) for x in words)

    def split(self, s):
        # Dynamic programming
        line = [self._split(x) for x in re.compile("[^a-zA-Z0-9'’,.$%()/-]+").split(s)]
        result = [item for sublist in line for item in sublist]
        return result

    def _split(self, s):
        # find the best match for the i first characters, assuming cost has
        # been built for the i-1 first characters.
        # returns a pair (match_cost, match_length).
        def best_match(i):
            candidates = enumerate(reversed(cost[max(0, i - self._maxword) : i]))
            return min(
                (c + self._word2cost.get(s[i - k - 1 : i].lower(), 9e999), k + 1)
                for k, c in candidates
            )

        # build the cost list
        cost = [0]
        for i in range(1, len(s) + 1):
            c, k = best_match(i)
            cost.append(c)

        # backtrack to recover the minimal-cost string.
        out = []
        i = len(s)
        while i > 0:
            c, k = best_match(i)
            assert c == cost[i]
            # handle digits, apostrophes, commas and brackets
            newToken = True
            if (not s[i - k : i] == "'") and (
                not s[i - k : i] == "’"
            ):  # ignore a lone apostrophe
                if len(out) > 0:
                    is_apostrophe = (
                        (out[-1] == "'s")
                        or (out[-1] == "’s")
                        or (out[-1] == "'")
                        or (out[-1] == "’")
                    )
                    is_comma = (out[-1][0] == ",") or (
                        s[i - 2].isdigit() and s[i - 1] == "," and out[-1][0].isdigit()
                    )
                    is_period = (out[-1][0] == ".") or (s[i - 1] == ".")
                    is_digit = s[i - 1].isdigit() and out[-1][0].isdigit()
                    is_bracket = (out[-1][0] == ")") or (s[i - 1] == "(")
                    is_dollar = (s[i - 1].isdigit() and out[-1][0] == "$") or (
                        out[-1][0].isdigit() and s[i - 1] == "$"
                    )
                    is_percent = (s[i - 1].isdigit() and out[-1][0] == "%") or (
                        out[-1][0].isdigit() and s[i - 1] == "%"
                    )

                    if (
                        is_apostrophe
                        or is_comma
                        or is_period
                        or is_digit
                        or is_bracket
                        or is_dollar
                        or is_percent
                    ):
                        if is_dollar or is_percent:
                            out[-1] = s[i - k : i] + " " + out[-1]
                        else:
                            out[-1] = (
                                s[i - k : i] + out[-1]
                            )  # combine current token with previous token
                        newToken = False

            if newToken:
                out.append(s[i - k : i])

            i -= k

        return reversed(out)
