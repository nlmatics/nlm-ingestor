import unittest

from ingestor import formatter
from ingestor import processors as pro


def fun(x):
    return x + 1


def get_result(blocks):
    result = []
    for block in blocks:
        result.append(block["block_text"])
    return result


def get_class(blocks):
    result = []
    for block in blocks:
        result.append(block["block_type"])
    return result


class MyTest(unittest.TestCase):
    def test_mixed_cased_words(self):
        self.assertEqual(formatter.fix_mixedcase_words("L.P."), "L.P.")
        self.assertEqual(formatter.fix_mixedcase_words("GoAT"), "Goat")
        self.assertEqual(formatter.fix_mixedcase_words("Goat"), "Goat")
        self.assertEqual(formatter.fix_mixedcase_words("Hello"), "Hello")
        self.assertEqual(formatter.fix_mixedcase_words("HEllo"), "HELLO")
        self.assertEqual(formatter.fix_mixedcase_words("heLLo"), "hello")

    def test_spaced_characters(self):
        result = pro.fix_spaced_characters("e x e c u t i v e summary")
        self.assertEqual(result, "executive summary")

        result = pro.fix_spaced_characters("e x e c u t i v e s u m m a r y")
        self.assertEqual(result, "executive summary")

        result = pro.fix_spaced_characters("e x e c u t i v e s u m m a r y".upper())
        self.assertEqual(result, "Executive Summary")

    def test_line_join(self):
        lines = [
            "Cushman & Wakefield Equity, Debt & Structured Finance has been exclusively retained by a joint "
            'venture of Stillman Development International and Daishin Securities (the "BORROWER" or '
            '"DEVELOPER") to arrange a $115.8 million construction loan for the redevelopment of the former',
            "Times Square Theater, located at 215 West 42nd Street",
            '(the "PROPERTY").',
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(
            [" ".join(lines)],
            get_result(result),
        )
        lines = [
            "THIS IS A CONFIDENTIAL MEMORANDUM intended solely for your own limited use to determine whether you have an interest in providing acquisition financing",
            "for 1375 Broadway (the “PROPERTY”). Cushman & Wakefield, Inc. (the “ADVISOR”) has been exclusively retained by an affiliate of Savanna Real Estate Fund (the “OWNER”) in this financing effort.",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual([" ".join(lines)], get_result(result))

        lines = [
            "Of the $31.6 million of underwritten tenant improvements and leasing costs, ~$19.3 million is budgeted to re-tenant/renew the 138,000 square feet (as remeasured) of Anchin space upon roll",
            "in October 2023",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual([" ".join(lines)], get_result(result))

        lines = [
            "(a) a “person” or",
            "“group” within the meaning of Section 13(d) of the Exchange Act, other than the Company, its Subsidiaries",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual([" ".join(lines)], get_result(result))

        lines = [
            "awards and citations for design excellence, including",
            "Royal Institute of British Architects (RIBA), Royal Fine",
            "Art Commission (RFAC) and American Institute of",
        ]

        result = pro.clean_lines(lines)
        self.assertEqual([" ".join(lines)], get_result(result))

        # lines = [
        #     "A few things must be taken into consideration:",
        #     "(a) a “person” or “group” within the meaning of Section 13(d) of the Exchange Act, other than something.",
        # ]
        # result = pro.clean_lines(lines)
        # self.assertEqual(lines, get_result(result))

        lines = [
            "Sources Amount per GSF per ZFA per NSF % of Total",
            "Construction Loan $43,387,000 $632 $886 $868 66.8%",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(len(result), 2)

        lines = [
            "Unlevered Cash Flow Summary Development Costs (ex-Debt Costs)",
            "have been very high recently",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["block_type"], "para")
        lines = [
            "Located between Wythe Avenue and Berry Street, the Project will",
            "span a total of 68,599 gross square feet and rise seven stories.",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(
            [
                "Located between Wythe Avenue and Berry Street, the Project will span a total of 68,599 gross square feet and rise seven stories.",
            ],
            get_result(result),
        )

        lines = ["line one ", "line 2"]
        result = pro.clean_lines(lines)
        self.assertEqual(["line one line 2"], get_result(result))

        lines = ["line one.", "line 2"]
        result = pro.clean_lines(lines)
        self.assertEqual(["line one. line 2"], get_result(result))

        lines = ["line one. ", "line 2"]
        result = pro.clean_lines(lines)
        self.assertEqual(["line one. line 2"], get_result(result))

        lines = ["Name Value", "Ambika 20"]
        result = pro.clean_lines(lines)
        self.assertEqual(["Name Value", "Ambika 20"], get_result(result))

        lines = ["and in the month of ", "October, you can pick apples."]
        result = pro.clean_lines(lines)
        self.assertEqual(
            ["and in the month of October, you can pick apples."],
            get_result(result),
        )

        lines = ["PROJECT OVERVIEW", "This project started out really well."]
        result = pro.clean_lines(lines)
        self.assertEqual(
            ["PROJECT OVERVIEW", "This project started out really well."],
            get_result(result),
        )

        lines = [
            "NOI $690,922 $1,081,379 $1,334,083 $1,917,111 $2,177,044 $2,236,895",
            "Detailed Breakdown is located on pages 13-17.",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(lines, get_result(result))

        # lines = [
        #     "and in the month of October, you can pick apples",
        #     "- Stuff is good",
        # ]
        # expected_result = [
        #     "and in the month of October, you can pick apples",
        #     "Stuff is good",
        # ]
        # result = pro.clean_lines(lines)
        # self.assertEqual(expected_result, get_result(result))

        lines = [
            "% PER KEY",
            "Hard Costs 60,750,000 50.63% $187,500",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(get_result(result), lines)

        lines = [
            "ROOMS $15,721 46.5% $350.2 $18,106 48.2% $388.5 $20,499 50.4% $426.5 $21,399 50.7% $443.5 $21,971 50.7% $456.0",
            "FOOD & BEVERAGE $12,752 37.7% $284.1 $13,536 36.1% $290.4 $13,942 34.3% $290.1 $14,366 34.0% $297.7 $14,756 34.0% $306.3",
        ]
        result = pro.clean_lines(lines)

        self.assertEqual(get_result(result), lines)

        lines = [
            "TOTAL SOURCES $120,000,000 100.00% $370,370",
            "% PER KEY",
            "Hard Costs 60,750,000 50.63% $187,500",
            "Contingencies & Developer Fee 7,000,000 5.83% $21,605",
        ]
        result = pro.clean_lines(lines)

        self.assertEqual(get_result(result), lines)

        lines = [
            "continued demand for this type of condominium product in ",
            "Manhattan.",
        ]
        result = pro.clean_lines(lines)
        self.assertEqual(
            get_result(result),
            ["continued demand for this type of condominium product in Manhattan."],
        )
        lines = [
            "OMH’S common stock is traded on the NYSE under the symbol “OMF.” OMH is incorporated in Delaware and SFC "
            "is incorporated in Indiana.Our executive offices are located at 601 N.w.",
            "Second Street, Evansville, Indiana 47708. Our telephone number is (812) 424-8031. Our Internet address "
            "is www.onemainfinancial.com. This is an interactive textual reference only, meaning that the information "
            "contained on the website is not part of this prospectus and is not incorporated into this prospectus or "
            "any accompanying prospectus supplement by reference.",
        ]
        result = pro.clean_lines(lines)
        # self.assertEqual(
        #     [" ".join(lines)], get_result(result),
        # )
        # This is a tricky one
        # lines = ['by the end of',
        #         'March 2019']
        # result = pro.clean_lines(lines)
        # self.assertEqual(result, ["by the end of March 2019"])
