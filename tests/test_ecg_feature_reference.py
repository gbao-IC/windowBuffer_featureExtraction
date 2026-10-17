import sys
from pathlib import Path
import unittest
from fractions import Fraction
import random
import ast
import math
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import ecg_feature_reference as f

class FeatureReferenceTests(unittest.TestCase):
    def test_all_cases_independent_decimal(self):
        for c in f.cases():
            with self.subTest(c['name']):
                self.assertEqual(f.fixed_features(c['samples'],*c['rr_ticks'])['encoded'],f.decimal_encoded(c['samples'],*c['rr_ticks']))
    def test_hand_calculated_zero_and_negative_constant(self):
        x=f.fixed_features([0]*347,180,360)['encoded']
        self.assertEqual(x[:8],[0]*8)
        self.assertEqual(x[8:10],[2**31,2**32]);self.assertEqual(x[11],-2**31)
        y=f.fixed_features([-32768]*347,288,288)['encoded']
        self.assertEqual([y[i] for i in [0,1,2,3,4,7]],[32768*2**32,0,32768*2**32,0,0,-32768*2**32])
    def test_zero_signs_and_half_boundary(self):
        x=f.fixed_features([-1,0,1]+[1]*344,1,1)
        self.assertEqual(x['stats']['zero_changes'],2)
        self.assertEqual(x['encoded'][3],f.rne(Fraction(2*2**32,347)))
        a=f.fixed_features([0]*172+[1]+[0]*174,1,1)
        b=f.fixed_features([0]*173+[1]+[0]*173,1,1)
        self.assertEqual(a['stats']['half1_squares'],1);self.assertEqual(a['stats']['half2_squares'],0)
        self.assertEqual(b['stats']['half1_squares'],0);self.assertEqual(b['stats']['half2_squares'],1)
        self.assertEqual(a['encoded'][5],15*2**32)
    def test_rounding_signed_ties(self):
        self.assertEqual([f.rne(Fraction(x,2)) for x in [-5,-3,-1,1,3,5]],[-2,-2,0,0,2,2])
    def test_random_full_domain_oracle(self):
        rng=random.Random(192347)
        for _ in range(100):
            x=[rng.randrange(-32768,32768) for _ in range(347)];r=rng.randrange(2**32);p=rng.randrange(2**32)
            self.assertEqual(f.fixed_features(x,r,p)['encoded'],f.decimal_encoded(x,r,p))
    def test_input_contract_rejects_invalid_values(self):
        for x,r,p in [([0]*346,1,1),([32768]*347,1,1),([-32769]*347,1,1),([0.0]*347,1,1),([0]*347,-1,0),([0]*347,0,2**32)]:
            with self.assertRaises(ValueError):f.fixed_features(x,r,p)
    def test_phase1a_float_reference_same_integer_inputs(self):
        from ecg_reference import extract_features, FEATURES
        self.assertEqual(tuple(FEATURES),f.FEATURES)
        for c in f.cases():
            rr,pv=c['rr_ticks']
            if not rr or not pv:continue # Phase1A validates positive RR.
            old=extract_features(c['samples'],rr/360,pv/360)
            ideal=f.decimal_features(c['samples'],rr,pv)
            for a,b in zip(old,ideal):self.assertTrue(math.isclose(a,float(b),rel_tol=2e-14,abs_tol=1e-12),(c['name'],a,b))
    def test_training_function_float64_count_domain(self):
        try:import numpy as np
        except ImportError:self.skipTest('NOT RUN numpy unavailable')
        path=Path(__file__).resolve().parents[2]/'AI_FSM_ECG/create_dataset.py'
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='extract_12_features')
        self.assertEqual([x.id for x in next(x for x in fn.body if isinstance(x,ast.Return)).value.elts],list(f.FEATURES))
        env={'np':np};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),env)
        for c in f.cases():
            rr,pv=c['rr_ticks']
            actual=env['extract_12_features'](np.array(c['samples'],dtype=np.float64),rr/360,pv/360)
            for a,b in zip(actual,f.decimal_features(c['samples'],rr,pv)):
                self.assertTrue(math.isclose(a,float(b),rel_tol=2e-14,abs_tol=1e-12),(c['name'],a,b))

if __name__=='__main__':unittest.main(verbosity=2)
