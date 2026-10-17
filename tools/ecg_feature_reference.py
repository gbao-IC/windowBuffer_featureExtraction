"""Phase3C count-domain references. No import/execution of training source.

Integer/Fraction oracle and independent high-precision Decimal oracle; original
Phase1A references and vectors remain immutable. Not a waveform scaling policy.
"""
import argparse
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random

FEATURES = ('f_rms', 'f_var', 'f_peak', 'f_zc', 'f_ptp', 'f_crest',
            'f_half_ratio', 'f_max', 'f_rr', 'f_rr_prev', 'f_rr_ratio', 'f_rr_diff')
N, F, RF = 347, 32, 48


def validate(samples, current, previous):
    if len(samples) != N or any(type(x) is not int or not -32768 <= x <= 32767 for x in samples):
        raise ValueError('Exactly 347 signed16 integer samples required')
    if any(type(t) is not int or not 0 <= t < 2**32 for t in (current, previous)):
        raise ValueError('RR metadata must be uint32 ticks')


def rne(value):
    value = Fraction(value)
    q, r = divmod(value.numerator, value.denominator)
    return q + (2*r > value.denominator or (2*r == value.denominator and q & 1))


def root_rne(total, count):
    # Independent integer oracle: compare rational input to squared midpoint.
    a = total << (2*RF)
    root = math.isqrt(a // count)
    cmp = 4*a - count*(2*root+1)**2
    return root + (cmp > 0 or (cmp == 0 and root & 1))


def fixed_features(samples, current, previous):
    validate(samples, current, previous)
    s = sum(samples)
    t = sum(x*x for x in samples)
    a = sum(x*x for x in samples[:173]); b = sum(x*x for x in samples[173:])
    signs = [(x > 0) - (x < 0) for x in samples]
    zc = sum(x != y for x, y in zip(signs, signs[1:]))
    peak = max(map(abs, samples)); hi, lo = max(samples), min(samples)
    u, v, w = (root_rne(total, count) for total, count in ((t,N),(a,173),(b,174)))
    eps = Fraction(1,10**9)
    real = [Fraction(u,2**RF), Fraction(N*t-s*s,N*N), peak, Fraction(zc,N), hi-lo,
            min(Fraction(15), Fraction(peak)/(Fraction(u,2**RF)+eps)),
            Fraction(v,2**RF)/(Fraction(w,2**RF)+eps), hi,
            Fraction(current,360), Fraction(previous,360),
            Fraction(current*10**9,previous*10**9+360), Fraction(current-previous,360)]
    words = [rne(x*2**F) for x in real]
    if any(not -2**95 <= x < 2**95 for x in words): raise OverflowError('signed96 output')
    assert -(2**24) <= s < 2**24 and t < 2**39 and a < 2**38 and b < 2**38
    return {'encoded':words, 'root_f48':[u,v,w],
            'stats':dict(sum=s,sum_squares=t,half1_squares=a,half2_squares=b,peak=peak,minimum=lo,maximum=hi,zero_changes=zc)}


def decimal_features(samples, current, previous, quantized_roots=False):
    """Separate algebra: Decimal mean-centered variance; Decimal square roots."""
    validate(samples,current,previous)
    with localcontext() as ctx:
        ctx.prec=100
        x=list(map(Decimal,samples)); mean=sum(x)/N
        rms=(sum(y*y for y in x)/N).sqrt()
        h1=(sum(y*y for y in x[:173])/173).sqrt()
        h2=(sum(y*y for y in x[173:])/174).sqrt()
        if quantized_roots:
            rms,h1,h2=[(v*2**RF).to_integral_value(rounding=ROUND_HALF_EVEN)/2**RF for v in (rms,h1,h2)]
        zc=sum((a>0)-(a<0)!=(b>0)-(b<0) for a,b in zip(samples,samples[1:]))
        rr,pv=Decimal(current)/360,Decimal(previous)/360
        eps=Decimal('0.000000001'); peak=max(abs(y) for y in x)
        return [rms,sum((y-mean)**2 for y in x)/N,peak,Decimal(zc)/N,max(x)-min(x),
                min(Decimal(15),peak/(rms+eps)),h1/(h2+eps),max(x),rr,pv,rr/(pv+eps),rr-pv]


def decimal_encoded(samples,current,previous):
    with localcontext() as ctx:
        ctx.prec=100
        return [int((x*2**F).to_integral_value(rounding=ROUND_HALF_EVEN))
                for x in decimal_features(samples,current,previous,True)]


def cases():
    result=[]
    def add(name,x,rr=288,prev=288): result.append(dict(name=name,samples=x,rr_ticks=[rr,prev]))
    add('zero',[0]*N)
    add('constant_positive',[123]*N,180,360)
    add('constant_negative',[-123]*N,360,180)
    add('signed16_min',[-32768]*N)
    add('signed16_max',[32767]*N)
    add('alternating_extremes',[-32768 if i%2==0 else 32767 for i in range(N)])
    add('negative_zero_positive',[(i%3-1)*7 for i in range(N)])
    add('zeros_do_not_double_count',[0,0,-3,-3,0,0,4,4,0]+[0]*(N-9))
    add('first_impulse',[32767]+[0]*(N-1))
    add('last_impulse',[0]*(N-1)+[-32768])
    add('half2_zero',[-32768]*173+[0]*174)
    add('half1_zero',[0]*173+[32767]*174)
    add('split_172',[0]*172+[100]+[0]*174)
    add('split_173',[0]*173+[100]+[0]*173)
    add('all_negative',[-1-(i%97) for i in range(N)],1,2)
    add('rr_zero',[1]*N,0,0)
    add('rr_previous_zero',[2]*N,2**32-1,0)
    add('rr_max_equal',[-2]*N,2**32-1,2**32-1)
    add('rr_negative_extreme',[3]*N,0,2**32-1)
    add('rr_positive_extreme',[-3]*N,2**32-1,1)
    rng=random.Random(0x3c347)
    for i in range(8): add('random_'+str(i),[rng.randrange(-32768,32768) for _ in range(N)],rng.randrange(2**32),rng.randrange(2**32))
    return result


def arithmetic_cases():
    rng=random.Random(0x3c192)
    pairs=[(0,1),(1,0),(0,0),(2**192-1,1),(2**192-1,2**192-1),
           (2**192-1,2**191),(2**191,2**192-1),(5,2),(7,2)]
    pairs += [(rng.getrandbits(192),rng.getrandbits(192) or 1) for _ in range(64)]
    rows=[]
    for a,b in pairs:
        q,r=divmod(a,b) if b else (0,0)
        rows.append([0,a,b,q,r,int(b==0)])
    for a in [0,1,2,3,4,8,9,15,16,2**192-1,2**190,2**128-1]+[rng.getrandbits(192) for _ in range(64)]:
        q=math.isqrt(a);rows.append([1,a,0,q,a-q*q,0])
    return rows


def export(directory):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    records=cases(); maximum=[Decimal(0)]*12
    for case in records:
        x=case['samples'];rr,pv=case['rr_ticks']; fixed=fixed_features(x,rr,pv)
        assert fixed['encoded']==decimal_encoded(x,rr,pv),case['name']
        ideal=decimal_features(x,rr,pv)
        with localcontext() as ctx:
            ctx.prec=100
            errors=[abs(Decimal(v)/2**F-e) for v,e in zip(fixed['encoded'],ideal)]
        maximum=[max(a,b) for a,b in zip(maximum,errors)]
        case.update(fixed);case['ideal_decimal']=[str(v) for v in ideal];case['absolute_error']=[str(v) for v in errors]
    # Quantization budget: root error amplified by epsilon only in half_ratio.
    limits=[Decimal('0.000000000117')]*12; limits[6]=Decimal('0.000002')
    assert all(e<=lim for e,lim in zip(maximum,limits)),list(zip(FEATURES,maximum))
    package={'contract':'signed16-counts_f48-roots_signed96-f32_v1','feature_order':FEATURES,
             'count':len(records),'cases':records,'max_absolute_error':[str(x) for x in maximum],
             'error_budget':[str(x) for x in limits],'reference_parity':'PASS','training_preprocessing_parity':'NOT RUN'}
    mathcases=arithmetic_cases()
    contents={'features.json':json.dumps(package,indent=2)+'\n',
              'samples.mem':''.join(f'{x&65535:04x}\n' for c in records for x in c['samples']),
              'expected.mem':''.join(f'{x%(2**96):024x}\n' for c in records for x in c['encoded']),
              'rr.mem':''.join(f'{x:08x}\n' for c in records for x in c['rr_ticks']),
              'math.mem':''.join(f'{x:048x}\n' for row in mathcases for x in row)}
    for name,content in contents.items():
        with (directory/name).open('x',encoding='ascii',newline='\n') as out:out.write(content)
    print(f'PASS feature_reference cases={len(records)} decimal_parity=bit_exact math_cases={len(mathcases)}')
    return package


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    export(parser.parse_args().output)
