import unittest

from ingestor import line_parser as lp


class MyTest(unittest.TestCase):
    def test_incomplete_line(self):
        self.assertTrue(lp.Line("This is a incomplete line,").incomplete_line)
        self.assertTrue(
            lp.Line(
                "Upon the closing of the transactions contemplated by the Transaction Agreement, Leslie H.",
            ).incomplete_line,
        )
        self.assertTrue(
            lp.Line(
                "Cushman & Wakefield Equity, Debt & Structured Finance has been exclusively retained by affiliates of Amstar and Wildflower Ltd.",
            ).incomplete_line,
        )
        self.assertTrue(
            lp.Line("Our executive offices are located at 601 N.w.").incomplete_line,
        )
        self.assertTrue(lp.Line("Our executive name is XYZ Inc.").incomplete_line)
        self.assertFalse(
            lp.Line(
                "Apple Computers has reported the best quarter ever.",
            ).incomplete_line,
        )
        self.assertFalse(lp.Line("Apple Revenue.").incomplete_line)
        self.assertFalse(lp.Line("Apple Revenue: 2,000 3,000").incomplete_line)

    def test_ends_with_abbreviation(self):
        self.assertTrue(
            lp.Line(
                "Upon the closing of the transactions contemplated by the Transaction Agreement, Leslie H.",
            ).ends_with_abbreviation,
        )
        self.assertTrue(
            lp.Line(
                "Cushman & Wakefield Equity, Debt & Structured Finance has been exclusively retained by affiliates of Amstar and Wildflower Ltd.",
            ).ends_with_abbreviation,
        )
        self.assertTrue(
            lp.Line(
                "Our executive offices are located at 601 N.w.",
            ).ends_with_abbreviation,
        )
        self.assertTrue(
            lp.Line("Our executive name is XYZ Inc.").ends_with_abbreviation,
        )

    def test_numbers(self):
        self.assertTrue(lp.Word("($10,000)").is_number)
        self.assertTrue(lp.Word("10,000").is_number)
        self.assertEqual(lp.Word("10,000").num_digits, 5)
        self.assertTrue(lp.Word("$10,000").is_dollar)
        self.assertEqual(lp.Word("$10,000").num_digits, 5)
        self.assertEqual(lp.Word("$10,000,000").num_digits, 8)
        self.assertTrue(lp.Word("10.34%").is_percent)
        self.assertTrue(lp.Word("10.34%").is_number)
        self.assertEqual(lp.Word("10.34%").num_digits, 2)
        self.assertEqual(lp.Word("10").num_digits, 2)
        self.assertTrue(lp.Word("10$").is_dollar)
        self.assertTrue(lp.Word("10m").is_million)
        self.assertFalse(lp.Word("1x000").is_year)
        self.assertFalse(lp.Word("1,000").is_year)
        self.assertTrue(lp.Word("2020").is_year)
        self.assertTrue(lp.Word("10-20").is_number_range)
        # self.assertTrue(lp.Word("xiv").is_roman_numbered) # 'is_roman_numbered' attribute has been deleted
        # self.assertTrue(lp.Word("III").is_roman_numbered) # 'is_roman_numbered' attribute has been deleted

    def test_numbered_line(self):

        # self.assertTrue(lp.Line("10. Testing").integer_numbered_line)
        self.assertTrue(lp.Line("10.12 Testing").integer_numbered_line)
        # self.assertTrue(lp.Line("10 Testing").integer_numbered_line)
        self.assertTrue(lp.Line("i. Testing").roman_numbered_line)
        self.assertTrue(lp.Line("i. Testing").numbered_line)
        self.assertTrue(lp.Line("a. Testing").numbered_line)
        self.assertTrue(lp.Line("10.b Testing").numbered_line)
        self.assertFalse(lp.Line("i do").numbered_line)
        self.assertFalse(lp.Line("$0.7656 per share (the “Per Share Purchase Price”).").numbered_line)
        self.assertTrue(lp.Line("iv) Testing").roman_numbered_line)
        self.assertTrue(lp.Line("(iv) Testing").roman_numbered_line)
        self.assertFalse(lp.Line("Testing").integer_numbered_line)
        self.assertFalse(lp.Line("I am a disco dancer").roman_numbered_line)
        self.assertFalse(lp.Line("a cow is eating grass").letter_numbered_line)

        self.assertFalse(lp.Line("I am a disco dancer").ends_with_period)
        self.assertFalse(lp.Line("I am a disco dancer Mr.").ends_with_period)
        self.assertTrue(lp.Line("I am a disco dancer.").ends_with_period)
        self.assertTrue(lp.Line("1.3.4 is a numbered line").integer_numbered_line)
        # self.assertTrue(lp.Line("1. is a numbered line").integer_numbered_line)
        self.assertTrue(lp.Line("1.22 is a numbered line").integer_numbered_line)
        # self.assertTrue(lp.Line("1 is a numbered line").integer_numbered_line)
        self.assertTrue(lp.Line("44.44 is a numbered line").integer_numbered_line)
        self.assertFalse(lp.Line("441.44 is NOT a numbered line").integer_numbered_line)
        self.assertFalse(lp.Line("1972 is NOT a numbered line").integer_numbered_line)
        self.assertFalse(
            lp.Line(
                "or completeness of this memorandum or any of its contents, and no legal commitments or obligations shall arise by reason of this",
            ).numbered_line,
        )
        self.assertTrue(
            lp.Line(
                "(a) a “person” or “group” within the meaning of Section 13(d) of the Exchange Act, other than the",
            ).letter_numbered_line,
        )

        self.assertTrue(lp.Line("S1").letter_numbered_line)
        # self.assertTrue(lp.Line("JLL-33").letter_numbered_line)
        # self.assertTrue(lp.Line("A-1").letter_numbered_line)
        # self.assertTrue(lp.Line("xi-10").letter_numbered_line)
        # self.assertTrue(lp.Line("S-11").letter_numbered_line)
        self.assertFalse(lp.Line("(MM)").letter_numbered_line)
        self.assertFalse(lp.Line("A cow is eating grass").letter_numbered_line)
        self.assertFalse(lp.Line("I enjoy coding").letter_numbered_line)
        self.assertFalse(
            lp.Line(
                "L Beam company is making a new device to compete with Apple",
            ).letter_numbered_line,
        )
        self.assertTrue(lp.Line("(A) This is good").letter_numbered_line)
        self.assertTrue(
            lp.Line("A. Notwithstanding the foregoing").letter_numbered_line,
        )

    def test_continuing_line(self):
        # &
        self.assertTrue(
            lp.Line(
                "or completeness of this memorandum or any of its contents, and no legal commitments or obligations shall arise by reason of this",
            ).continuing_line,
        )
        self.assertTrue(lp.Line("& Parson and Sons").continuing_line)
        self.assertFalse(
            lp.Line(
                "(a) a “person” or “group” within the meaning of Section 13(d) of the Exchange Act, other than the",
            ).continuing_line,
        )

    def test_start_number(self):
        line = lp.Line("10.12 Testing")
        self.assertEqual("10.12", line.start_number)
        self.assertEqual("Testing", line.line_without_number)
        line = lp.Line("iv) Testing")
        self.assertEqual("iv", line.start_number)
        self.assertEqual("Testing", line.line_without_number)

    def test_counts(self):
        self.assertEqual(lp.Line("10. Testing").title_word_count, 1)
        self.assertEqual(lp.Line("10. My Testing").title_word_count, 2)
        self.assertEqual(lp.Line("10. MY TESTING").title_word_count, 2)

        line = lp.Line("I am a Disco Dancer")
        self.assertEqual(line.stop_word_count, 3)
        self.assertEqual(line.eff_word_count, 2)
        self.assertEqual(lp.Line("I am a disco dancer").word_count, 5)
        self.assertEqual(lp.Line("I am a disco dancer").word_count, 5)
        self.assertEqual(lp.Line("Manhattan.").number_count, 0)
        self.assertTrue(lp.Line("E x e c u t i v e Summary").has_spaced_characters)
        self.assertTrue(lp.Line("D n B").has_spaced_characters)
        self.assertTrue(
            lp.Line("E x e c u t i v e S u m m a r y").has_spaced_characters,
        )
        self.assertFalse(lp.Line("Executive Summary").has_spaced_characters)

    def test_is_table_row(self):
        self.assertFalse(
            lp.Line(
                "York, New York 10014 (the “PROPERTY”, “DEVELOPMENT” or",
            ).is_table_row,
        )
        self.assertFalse(
            lp.Line(
                "Times Square Theater, located at 215 West 42nd Street",
            ).is_table_row,
        )
        self.assertFalse(lp.Line("in October 2023").is_table_row)
        self.assertTrue(
            lp.Line(
                "Net Debt (685,365,480)$ (685,145,818)$ (683,596,099)$ (680,659,153)$ (676,275,920)$ (670,384,913)$ (662,922,125)$ (653,820,919)$ (643,011,932)$",
            ).is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "Less: Sales Costs (4.14%) ($2,795,402) ($2,836,463) ($2,877,523) ($2,918,584) ($2,959,644)",
            ).is_table_row,
        )
        self.assertTrue(
            lp.Line("Construction Loan - Mezz 20% $20,000,000").is_table_row,
        )
        self.assertTrue(lp.Line("Net Site Area 2.08 Acres").is_table_row)
        self.assertTrue(
            lp.Line(
                "Washington Metro Area 415,357 $1,748 $2.00 2.6% 2.2% 13,618 9,605",
            ).is_table_row,
        )
        self.assertTrue(lp.Line("Executive Summary 1").is_table_row)
        self.assertFalse(lp.Line("Manhattan.").is_table_row)
        self.assertTrue(
            lp.Line(
                "Elliott Bay Office PARK 1980 225,615 $390,000 $60,500,000 $38,333,333",
            ).is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "14.4% 14.2% 9.1% 20.0% 22.4% 17.8% 9.3% 14.4% 21.6% 18.7% 22.6%21.8% 12.1% 14.4% 37.4% 13.0%",
            ).is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "Income $1,307,248 $1,770,220 $2,097,548 $2,724,973 $3,009,633 $3,095,325",
            ).is_table_row,
        )
        self.assertFalse(lp.Line("Hey there you owe me $20.00").is_table_row)
        self.assertTrue(lp.Line("Income $1,307,248").is_table_row)
        self.assertTrue(lp.Line("Ambika Sukla 20").is_table_row)
        self.assertTrue(lp.Line("0.0 1.0 2.0 3.0 4.0 5.0 6.0 7.0").is_table_row)
        self.assertFalse(lp.Line("line 3").is_table_row)
        self.assertTrue(
            lp.Line(
                "Total Controllable Expenses $3.07 $7,837 $1,982,761 $1,646,030 $1,688,654 $1,735,263 $1,775,679",
            ).is_table_row,
        )
        self.assertTrue(lp.Line("Total Debt 644,000,000$ 100.0%").is_table_row)
        self.assertTrue(
            lp.Line(
                "NOI $690,922 $1,081,379 $1,334,083 $1,917,111 $2,177,044 $2,236,895",
            ).is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "ROOMS $15,721 46.5% $350.2 $18,106 48.2% $388.5 $20,499 50.4% $426.5 $21,399 50.7% $443.5 $21,971 50.7% $456.0",
            ).is_table_row,
        )
        self.assertFalse(lp.Line("3. DEVELOPER OVERVIEW AND TRACK RECORD").is_table_row)
        self.assertFalse(lp.Line("CONFIDENTIAL FINANCING MEMORANDUM").is_table_row)
        self.assertFalse(lp.Line("STRONG DEMOGRAPHICS").is_table_row)
        self.assertFalse(lp.Line("5. MARKET OVERVIEW").is_table_row)
        # self.assertFalse(lp.Line("04 MARKET OVERVIEW").is_table_row)
        self.assertFalse(
            lp.Line("DISCLAIMER AND NOTICE OF CONFIDENTIALITY").is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "Less: Credit Loss / Vacancy Allowance -$2.30 -$1,440,000",
            ).is_table_row,
        )

        self.assertTrue(
            lp.Line(
                "Goldman sachs & co. llc $ 147,067,000 $ 183,834,000 $ 183,834,000 $ 294,133,000 $ 367,667,000 $ 294,134,000",
            ).is_table_row,
        )
        self.assertTrue(lp.Line("GAV Developed (US only): $1.1bn").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval Feb-17").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval Feb-17-19").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval Feb-17-2019").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval February-17").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval February-17-19").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval February-17-2019").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval 02/17/19").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval 02/17/19").is_table_row)
        self.assertTrue(lp.Line("NYC LPC Approval 02/17/2019").is_table_row)
        self.assertFalse(lp.Line("Sales Report for February").is_table_row)
        self.assertFalse(lp.Line("Sales Report for February-2019").is_table_row)
        self.assertFalse(
            lp.Line("DISCLAIMER AND NOTICE OF CONFIDENTIALITY").is_table_row,
        )
        self.assertTrue(
            lp.Line(
                "Less: Credit Loss / Vacancy Allowance -$2.30 -$1,440,000",
            ).is_table_row,
        )

        self.assertTrue(
            lp.Line(
                "Goldman sachs & co. llc $ 147,067,000 $ 183,834,000 $ 183,834,000 $ 294,133,000 $ 367,667,000 $ 294,134,000",
            ).is_table_row,
        )
        self.assertTrue(lp.Line("GAV Developed (US only): $1.1bn").is_table_row)
        self.assertFalse(lp.Line("Securities Exchange Act of 1934").is_table_row)
        self.assertFalse(lp.Line("November 2019").is_table_row)
        self.assertTrue(lp.Line("Free Rent Concessions (665,908) - - - -").is_table_row)
        self.assertTrue(
            lp.Line("30,000 square feet ................. 28 weeks").is_table_row,
        )

    def test_is_header(self):
        self.assertTrue(lp.Line("This is a Header").is_header)
        self.assertFalse(lp.Line("A Header this is Not,").is_header)

        self.assertFalse(
            lp.Line(
                """Christopher R. Herron chris.herron@ironhound.com Rob Vernicek
        robert.vernicek@ironhound.com Patrick Perone patrick.perone@ironhound.com Iron Hound Management Company,
        LLC has been retained as exclusive advisor to Triangle Assets (the "SPONSOR"), to arrange construction
        financing for the development of 303 East 44th Street (the "PROPERTY" or "PROJECT"), a proposed 122,
        734 gross square foot, unique luxury condominium tower located in Manhattan's Midtown East neighborhood on
        the northern block-front of East 44th Street between Second and First Avenues.""",
            ).is_header,
        )
        self.assertFalse(lp.Line("Sunset from").is_header)
        self.assertFalse(lp.Line("Stars: Don’t we know all there is to know?").is_header)

        self.assertFalse(
            lp.Line("• CONCRETE CAST-IN-PLACE (SEE STRUC. DWGS)").is_header,
        )
        self.assertFalse(
            lp.Line(
                "Net Debt (685,365,480)$ (685,145,818)$ (683,596,099)$ (680,659,153)$ (676,275,920)$ (670,384,913)$ (662,922,125)$ (653,820,919)$ (643,011,932)$",
            ).is_header,
        )

        self.assertTrue(lp.Line("% PER KEY").is_header)
        self.assertFalse(
            lp.Line(
                "1 Bedroom 5 13.2% 654 3,270 8.2% $1,036,763 $1,585 $5,183,814 7.5%",
            ).is_header,
        )
        self.assertFalse(
            lp.Line("7 10.20 11.00 77.60 C 3.00 2.5 1,382 $2,711,450 $1,962").is_header,
        )
        self.assertTrue(
            lp.Line("Sources Amount per GSF per ZFA per NSF % of Total").is_header,
        )
        self.assertFalse(
            lp.Line(
                "11 Jane does not have true comparables given the rare combination of location, entitlements, design, materials and the",
            ).is_header,
        )
        self.assertTrue(lp.Line("Section 1: Executive Summary JLL").is_header)
        self.assertFalse(lp.Line("Estreich & Company Page 35").is_header)
        # self.assertFalse(lp.Line("In a school:").is_header)
        self.assertTrue(lp.Line("In a School").is_header)
        self.assertTrue(lp.Line("VI. DEVELOPMENT TEAM").is_header)
        self.assertTrue(lp.Line("V. MARKET OVERVIEW").is_header)
        self.assertFalse(lp.Line("Manhattan.").is_header)
        self.assertFalse(
            lp.Line(
                "I recommend the following to help crews w/ their introductory flight on the Max:",
            ).is_header,
        )
        #        self.assertFalse(lp.Line("Elliott Management Corporation manages two funds, Elliott Associates, L.P. and Elliott International, L.P.,").is_header)

        self.assertFalse(lp.Line("i do").is_header)
        # need to figure out what broke this:
        # self.assertTrue(lp.Line("i. Do").is_header)
        self.assertTrue(lp.Line("NATIONAL LANDING & CRYSTAL CITY").is_header)
        self.assertTrue(
            lp.Line("LIMITED EXISTING COMPETITIVE PRODUCT IN OLD TOWN").is_header,
        )
        # todo - fix this
        # self.assertTrue(lp.Line("iv) Do").is_header)

        # self.assertFalse(lp.Line("0.0 1.0 2.0 3.0 4.0 5.0 6.0 7.0").is_header)
        # self.assertTrue(lp.Line("1 Do").is_header)
        self.assertFalse(lp.Line("10.1% Yield debt").is_header)
        self.assertFalse(lp.Line("1942 a Love Story").is_header)
        self.assertTrue(lp.Line("PROJECT OVERVIEW").is_header)
        self.assertTrue(lp.Line("PROPOSAL FOR SERVICES").is_header)
        self.assertTrue(lp.Line("Test").is_header)
        self.assertTrue(lp.Line("4. 400 WESTLAKE PROJECT"))
        self.assertTrue(lp.Line("13. Audit Rights").is_header)
        self.assertFalse(
            lp.Line(
                "Income $1,307,248 $1,770,220 $2,097,548 $2,724,973 $3,009,633 $3,095,325",
            ).is_header,
        )

        self.assertTrue(lp.Line("3. DEVELOPER OVERVIEW AND TRACK RECORD").is_header)
        self.assertTrue(lp.Line("DEVELOPMENT O V E R V I E W").is_header)
        # self.assertTrue(lp.Line("04 MARKET OVERVIEW").is_header)
        self.assertTrue(lp.Line("BUILDING SPECIFICATIONS CONTINUED").is_header)
        self.assertTrue(lp.Line("OUTSTANDING TRANSPORTATION INFRASTRUCTURE").is_header)
        self.assertTrue(lp.Line("DISCLAIMER AND NOTICE OF CONFIDENTIALITY").is_header)
        self.assertTrue(lp.Line("4. FEDERAL RESERVE BANK PROJECT").is_header)
        self.assertTrue(
            lp.Line(
                "3. Permissible Disclosures of Due Diligence Information",
            ).is_header,
        )
        self.assertFalse(
            lp.Line(
                "a 2005 rezoning, Williamsburg has emerged as one of the premier",
            ).is_header,
        )
        self.assertFalse(
            lp.Line(
                "This is a confidential memorandum intended solely for your limited use and benefit in determining whether you desire to express",
            ).is_header,
        )
        self.assertFalse(lp.Line("NYC LPC Approval Feb-17").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval Feb-17-19").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval Feb-17-2019").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval February-17").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval February-17-19").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval February-17-2019").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval 02/17").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval 02/17/19").is_header)
        self.assertFalse(lp.Line("NYC LPC Approval 02/17/2019").is_header)
        self.assertTrue(lp.Line("Sales Report for February").is_header)
        self.assertTrue(lp.Line("Sales Report for February-2019").is_header)

        # self.assertFalse(lp.Line("NOT BE DEEMED TO BE A REPRESENTATION OF THE STATE OF"))

        self.assertFalse(
            lp.Line(
                "Goldman sachs & co. llc $ 147,067,000 $ 183,834,000 $ 183,834,000 $ 294,133,000 $ 367,667,000 $ 294,134,000",
            ).is_header,
        )
        self.assertFalse(lp.Line("GAV Developed (US only): $1.1bn").is_header)
        self.assertTrue(
            lp.Line(
                "Section 2.08. Cancellation of Notes Paid, Converted, Etc.",
            ).is_header,
        )
        self.assertTrue(
            lp.Line("Section 7.03. No Responsibility for Recitals, Etc.").is_header,
        )
        self.assertTrue(lp.Line("Section 7.11. Succession by Merger, Etc.").is_header)
        self.assertTrue(lp.Line("Section 1.02 Rules of Construction.").is_header)
        self.assertTrue(lp.Line("Section 5.01 Lists of Holders.").is_header)
        self.assertFalse(
            lp.Line("Section 10.04, Section 13.02 and Section 14.03.").is_header,
        )
        self.assertFalse(
            lp.Line(
                "Section 2.08. refers to the cancellation of notes paid.",
            ).is_header,
        )

        self.assertTrue(lp.Line("Securities Exchange Act of 1934").is_header)
        self.assertFalse(lp.Line("Seattle, Washington 98109-5210").is_header)
        self.assertFalse(lp.Line("P.o. Box 81226").is_header)

    def test_is_list_item(self):
        # self.assertTrue(lp.Line("(a) a").is_list_item)
        # self.assertTrue(lp.Line("(A) a").is_list_item)
        # self.assertTrue(
        #     lp.Line("(A) a person or group within the meaning").is_list_item,
        # )
        # self.assertTrue(
        #     lp.Line(
        #         "(a) a “person” or “group” within the meaning of Section 13(d) of the Exchange Act, other than the",
        #     ).is_list_item,
        # )
        # self.assertTrue(
        #     lp.Line("• CONCRETE CAST-IN-PLACE (SEE STRUC. DWGS)").is_list_item,
        # )
        pass

    def test_is_zipcode_or_po(self):
        self.assertTrue(lp.Line("P.o. Box 81226").is_zipcode_or_po)
        self.assertTrue(lp.Line("Seattle, WA 98108-1226").is_zipcode_or_po)
        self.assertTrue(lp.Line("New York, New York 10166").is_zipcode_or_po)
        self.assertTrue(lp.Line("Minneapolis, Minnesota 55479").is_zipcode_or_po)
        self.assertTrue(lp.Line("Green Bay, WI 54303").is_zipcode_or_po)
        self.assertFalse(
            lp.Line(
                "of 101 North Phillips Avenue, Sioux Falls, SD 57104",
            ).is_zipcode_or_po,
        )

    def test_line_type(self):
        self.assertEqual(lp.Line("3.15 Vacancies").line_type, "header")
        # self.assertEqual(
        #     lp.Line("(A) a person or group within the meaning").line_type,
        #     "numbered_list_item",
        # )

    def test_non_ascii(self):
        lp.Line("½")
        pass

    def test_noun_chunks(self):
        line = lp.Line("Davis Polk & Wardwell LLP")
        self.assertEqual(line.noun_chunks, ["Davis Polk & Wardwell LLP"])
        line = lp.Line("I used to work for Morgan Stanley's New York office")
        self.assertListEqual(line.noun_chunks, ["Morgan Stanley", "New York"])
        line = lp.Line('Stock symbol of Morgan Stanley is "MS"')
        self.assertEqual(line.noun_chunks, ['MS', 'Morgan Stanley', 'Stock'])
        line = lp.Line('This non negotiable Service Agreement is ("Service Agreement")')
        self.assertEqual(line.noun_chunks, ['Service Agreement'])
        line = lp.Line("Skadden, Arps, Slate, Meagher & Flom LLP")
        self.assertEqual(line.noun_chunks, ["Skadden Arps Slate Meagher & Flom LLP"])
        line = lp.Line("There are 25 florrs in 150 Broadway and they are all oversold")
        self.assertEqual(line.noun_chunks, ["150 Broadway"])
        line = lp.Line("Series Seed 1 Preferred Stock, par value $0.00001 per share")
        self.assertEqual(line.noun_chunks, ["Series Seed 1 Preferred Stock"])
        line = lp.Line("1.3 that number of Shares set forth opposite such Investor’s name on Schedule A hereto "
                       "for a purchase price of $6.021 per share of Series B-1 Preferred Stock, $5.118 per share of "
                       "Series B-2 Preferred Stock and $4.817 per share of Series B-3 Preferred Stock, as applicable.")
        self.assertEqual(line.noun_chunks, ['Investor’s',
                                            'Schedule A',
                                            'Series B-1 Preferred Stock',
                                            'Series B-2 Preferred Stock',
                                            'Series B-3 Preferred Stock',
                                            'Shares'])

    def test_quotation_words(self):
        line = lp.Line('This company ("NLMatics") is refered as NLMatics')
        self.assertEqual(line.quoted_words, ["NLMatics"])
        line = lp.Line("Delta Airline 'DAL' went up 7.5% today \"Nov.4\"")
        self.assertEqual(line.quoted_words, ["DAL", "Nov.4"])


if __name__ == "__main__":
    unittest.main()
