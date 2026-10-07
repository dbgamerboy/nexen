import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from benefits_runtime import ProfileUpdate
import test_benefits_runtime as fixtures


class ProfilePatchTests(unittest.TestCase):
    setUp = fixtures.BenefitsRuntimeTests.setUp
    tearDown = fixtures.BenefitsRuntimeTests.tearDown

    def test_partial_location_preserves_known_facts(self):
        self.benefits.update_profile(ProfileUpdate(city='Old', county='County', household_size=3, gross_monthly_income=1000, cat_spay_needed=False))
        saved = self.benefits.update_profile(ProfileUpdate(city='Portland', county='Multnomah'))
        self.assertEqual(saved['facts']['household_size'], 3)
        self.assertEqual(saved['facts']['gross_monthly_income'], 1000)
        self.assertFalse(saved['facts']['cat_spay_needed'])

    def test_missing_values_are_not_invented(self):
        saved = self.benefits.update_profile(ProfileUpdate(city='Portland', county='Multnomah'))
        self.assertNotIn('cat_spay_needed', saved['facts'])
        self.assertNotIn('tax_issue_active', saved['facts'])
        self.assertIn('household size', saved['unknowns'])

    def test_explicit_clear_is_allowed(self):
        self.benefits.update_profile(ProfileUpdate(household_size=2, city='Portland'))
        saved = self.benefits.update_profile(ProfileUpdate(household_size=None))
        self.assertIsNone(saved['facts']['household_size'])
        self.assertEqual(saved['facts']['city'], 'Portland')

    def test_atomic_replace_failure_preserves_previous_file(self):
        before = self.profile.read_bytes()
        with patch('benefits_runtime.os.replace', side_effect=OSError('fixture replacement failure')):
            with self.assertRaises(OSError):
                self.benefits.update_profile(ProfileUpdate(city='Portland'))
        self.assertEqual(self.profile.read_bytes(), before)
        self.assertFalse(list(self.root.glob('.benefits-profile-*.tmp')))

    def test_corrupt_existing_profile_is_not_overwritten(self):
        self.profile.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(HTTPException):
            self.benefits.update_profile(ProfileUpdate(city='Portland'))
        self.assertEqual(self.profile.read_text(), '{invalid')

    def test_invalid_or_sensitive_fields_refused(self):
        for body in ({'ssn':'fixture'}, {'household_size':0}, {'city':'x'*81}, {'gross_monthly_income':-1}):
            with self.assertRaises(ValidationError):
                ProfileUpdate(**body)


if __name__ == '__main__':
    unittest.main()
