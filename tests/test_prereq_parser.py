import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from prereq_parser import parse_prerequisites, parse_course


class ParsePrerequisitesTest(unittest.TestCase):
    def test_empty_and_none(self):
        for text in ('', None, 'Prereq: None'):
            r = parse_prerequisites(text)
            self.assertEqual(r['prereq'], [])
            self.assertEqual(r['requirements'], [])

    def test_single_course(self):
        self.assertEqual(parse_prerequisites('Prereq: SYG 2000.')['prereq'], [['SYG2000']])

    def test_or_group(self):
        self.assertEqual(
            parse_prerequisites('Prereq: MET 1010 or GEO 2200 or GEO 2242.')['prereq'],
            [['MET1010', 'GEO2200', 'GEO2242']],
        )

    def test_and_of_or_groups_with_grade(self):
        r = parse_prerequisites(
            'Prereq: (COP 3504 or COP 3503) and COT 3100 and (MAC 2234 or MAC 2312 or MAC 2512 or MAC 3473), '
            'all with a minimum grade of C.'
        )
        self.assertEqual(
            r['prereq'],
            [['COP3504', 'COP3503'], ['COT3100'], ['MAC2234', 'MAC2312', 'MAC2512', 'MAC3473']],
        )
        self.assertEqual(r['minGrade'], 'C')

    def test_coreq_segment(self):
        r = parse_prerequisites('Prereq: ENU 4103.\nCoreq: ENU 4134.')
        self.assertEqual(r['prereq'], [['ENU4103']])
        self.assertEqual(r['coreq'], [['ENU4134']])

    def test_coreq_only(self):
        r = parse_prerequisites('Coreq: BOT 3503.')
        self.assertEqual(r['prereq'], [])
        self.assertEqual(r['coreq'], [['BOT3503']])

    def test_prereq_or_coreq_is_concurrent(self):
        r = parse_prerequisites('Prereq or coreq: CHM 2046L.')
        self.assertEqual(r['concurrent'], [['CHM2046L']])
        self.assertEqual(r['prereq'], [])

    def test_comma_list_ending_in_or_is_or(self):
        r = parse_prerequisites('Prereq: MAC 2311, MAC 2281, or MAC 3472.')
        self.assertEqual(r['prereq'], [['MAC2311', 'MAC2281', 'MAC3472']])

    def test_plain_comma_list_is_and(self):
        r = parse_prerequisites('Prereq: MAC 2311, MAC 2312, COP 3502.')
        self.assertEqual(r['prereq'], [['MAC2311'], ['MAC2312'], ['COP3502']])

    def test_semicolon_separates_and_clauses(self):
        r = parse_prerequisites('Prereq: MAC 2312 or MAC 2512; STA 2023.')
        self.assertEqual(r['prereq'], [['MAC2312', 'MAC2512'], ['STA2023']])

    def test_distributes_or_over_and(self):
        r = parse_prerequisites('Prereq: (MAC 2311 and COP 3502) or MAC 3473.')
        self.assertEqual(sorted(map(sorted, r['prereq'])), [['COP3502', 'MAC3473'], ['MAC2311', 'MAC3473']])

    def test_instructor_permission_makes_a_soft_group(self):
        r = parse_prerequisites('Prereq: MVS 1116 (with minimum grade of C) or Instructor Approval.')
        self.assertEqual(r['prereq'], [])
        self.assertEqual(r['softPrereq'], [['MVS1116']])
        self.assertEqual(r['minGrade'], 'C')

    def test_non_course_requirements_are_kept_as_text(self):
        r = parse_prerequisites('Prereq: Music major. Coreq: MUT 1122.')
        self.assertEqual(r['requirements'], ['Music major'])
        self.assertEqual(r['coreq'], [['MUT1122']])

    def test_standing_is_detected(self):
        r = parse_prerequisites('Prereq: Junior standing or higher.')
        self.assertEqual(r['standing'], 'junior')

    def test_credit_clauses_do_not_split_on_or(self):
        r = parse_prerequisites('Prereq: 3 credits of a JST or EUH or ASH or REL course.')
        self.assertEqual(r['prereq'], [])
        self.assertEqual(len(r['requirements']), 1)

    def test_recommended_courses_are_notes_not_requirements(self):
        r = parse_prerequisites('Prereq: MAC 2312 and (MAC 2512 or MAC 3473) with a minimum grade of C; MAS 3300 recommended.')
        self.assertEqual(r['prereq'], [['MAC2312'], ['MAC2512', 'MAC3473']])
        self.assertIn('MAS3300 recommended', r['notes'])

    def test_mixed_and_or_without_parens_is_flagged(self):
        self.assertTrue(parse_prerequisites('Prereq: MAC 2311 and COP 3502 or MAC 3473.')['ambiguous'])

    def test_self_reference_removed(self):
        r = parse_course({'code': 'MAC2311', 'prerequisites': 'Prereq: MAC 2311 or MAC 3472.'})
        self.assertEqual(r['prereq'], [['MAC3472']])

    def test_or_equivalent_is_a_note_not_an_alternative(self):
        r = parse_prerequisites('Prereq: BOT 3503 and HOS 4304 or equivalent.')
        self.assertEqual(r['prereq'], [['BOT3503'], ['HOS4304']])
        self.assertIn('equivalent courses are accepted', r['notes'])

    def test_comma_and_starts_a_new_clause(self):
        r = parse_prerequisites('Prereq: PHY 2061 or instructor permission, and MAP 2302.')
        self.assertEqual(r['prereq'], [['MAP2302']])
        self.assertEqual(r['softPrereq'], [['PHY2061']])

    def test_leading_credits_label_is_ignored(self):
        self.assertEqual(parse_prerequisites('Credits: 3; Prereq: MAC 2311.')['prereq'], [['MAC2311']])

    def test_standing_with_or_higher_is_one_requirement(self):
        r = parse_prerequisites('Prereq: (ACG 2021 and junior standing or higher) or (ACG 2021 and ECO 2023 and sophomore standing).')
        self.assertEqual(r['prereq'], [['ACG2021']])
        self.assertEqual(r['softPrereq'], [['ECO2023']])

    def test_credits_from_a_course_list(self):
        r = parse_prerequisites('Prereq: 6 credits from AFS 2002 or HUM 2420.')
        self.assertEqual(r['prereq'], [['AFS2002', 'HUM2420']])
        self.assertIn('6 credits needed from the courses listed', r['notes'])

    def test_code_glued_to_following_word(self):
        self.assertEqual(parse_prerequisites('Prereq: JPN 2231with a minimum grade of C.')['prereq'], [['JPN2231']])

    def test_never_raises_on_garbage(self):
        for text in ('Prereq: ((( and or ,,, ;;', 'Coreq:', 'Prereq or coreq: or coreq:', ')))'):
            parse_prerequisites(text)


if __name__ == '__main__':
    unittest.main()
