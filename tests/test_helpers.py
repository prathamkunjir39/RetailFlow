import unittest
from decimal import Decimal
from app import money, positive_int, decimal_input

class ValidationTests(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(money('12.345'), Decimal('12.35'))
    def test_zero_quantity_rejected(self):
        with self.assertRaises(ValueError):
            positive_int('0')
    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError):
            positive_int('-3')
    def test_valid_price(self):
        self.assertEqual(decimal_input('25.50'), Decimal('25.50'))
    def test_overprecision_rejected(self):
        with self.assertRaises(ValueError):
            decimal_input('25.555')
    def test_discount_over_100_rejected(self):
        with self.assertRaises(ValueError):
            decimal_input('101', allow_zero=True, maximum='100')

if __name__ == '__main__':
    unittest.main()
