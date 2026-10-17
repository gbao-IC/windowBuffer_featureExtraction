"""Phase3C repeatable count-domain feature verification; never overwrite evidence."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--questa-dir',type=Path,default=Path('C:/MentorGraphics/win64'))
    p.add_argument('--prior-regression',action='store_true',help='Run unchanged Phase3B runner (includes Phase3A and MLP) after new checks PASS')
    args=p.parse_args()
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='ECG':p.error('ECG branch required')
    build=ROOT/'build/phase3c'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');build.mkdir(parents=True,exist_ok=False)
    rtl=[ROOT/'rtl/ecg'/x for x in ['ecg_window_buffer.sv','ecg_feature_math.sv','ecg_feature_core.sv']]
    tb=[ROOT/'tb/ecg'/x for x in ['tb_ecg_feature_math.sv','tb_ecg_feature_core.sv']]
    sources=rtl+tb+[Path(__file__),ROOT/'tools/ecg_feature_reference.py',ROOT/'tests/test_ecg_feature_reference.py',ROOT/'tools/ecg_reference.py',ROOT/'docs/phase3c_numeric_contract.md']
    h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
    hashes={x.relative_to(ROOT).as_posix():h(x) for x in sources}
    checks=[]
    def run(name,cmd,marker=None,cwd=build,composite=False,timeout=180):
        print('RUN',name,flush=True)
        try:
            a=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
            text=a.stdout+a.stderr;code=a.returncode
        except (OSError,subprocess.TimeoutExpired) as exc:text=str(exc);code=-1
        log=build/(name+'.log');log.write_text(text,encoding='utf-8')
        errors=[line for line in text.splitlines() if re.search(r'\*\* (Error|Fatal)|\bFAIL\b',line)]
        ok=code==0 and (not errors or composite) and (not marker or marker in text)
        checks.append(dict(name=name,status='PASS' if ok else 'FAIL',exit_code=code,command=list(map(str,cmd)),cwd=str(cwd),log=log.relative_to(ROOT).as_posix(),errors=errors,warnings=[s for s in text.splitlines() if 'Warning:' in s],pass_lines=[s.strip('# ') for s in text.splitlines() if 'PASS ' in s]))
        print(checks[-1]['status'],name,flush=True)
        if not ok:print(text[-12000:],flush=True)
        return ok
    env=ROOT.parent/'.phase1a_env/Scripts/python.exe';python=env if env.is_file() else Path(sys.executable)
    unit=run('python_reference_tests',[python,'-B','-m','unittest','discover','-s','tests','-p','test_ecg_feature_reference.py','-v'],cwd=ROOT)
    generated=run('golden_generation',[python,'-B',ROOT/'tools/ecg_feature_reference.py','--output',build/'vectors'],'PASS feature_reference')
    success=False
    exe=lambda n:args.questa_dir/(n+'.exe')
    if generated and unit and all(exe(x).is_file() for x in ['vlog','vopt','vsim','vlib','vmap']):
        run('questa_version',[exe('vlog'),'-version'])
        ok=run('vlib',[exe('vlib'),'work'])
        ok=run('vmap_init',[exe('vmap'),'-c']) and ok
        ok=run('vmap_work',[exe('vmap'),'work','work']) and ok
        ok=ok and run('feature_lint_compile',[exe('vlog'),'-sv','-lint',*rtl,*tb])
        ok=ok and run('feature_elaboration',[exe('vopt'),'work.ecg_feature_core','-o','feature_elab'])
        if ok:
            cases=json.loads((build/'vectors/features.json').read_text())['count']
            arithmetic=(build/'vectors/math.mem').read_text().count('\n')//6
            outcomes=[]
            for name,top,params in [('arithmetic','tb_ecg_feature_math',[f'+VECTORS={(build/"vectors/math.mem").as_posix()}',f'+CASES={arithmetic}']),('features_direct','tb_ecg_feature_core',['-gSTALLED=0',f'+VECTORS={(build/"vectors").as_posix()}',f'+CASES={cases}']),('features_stalled','tb_ecg_feature_core',['-gSTALLED=1',f'+VECTORS={(build/"vectors").as_posix()}',f'+CASES={cases}'])]:
                wave=build/(name+'.vcd');macro=build/(name+'.do')
                if top=='tb_ecg_feature_math':signals='clk rst_n abort start sqrt_op numerator denominator busy done error quotient remainder'
                else:signals='clk rst_n flush source_loss start ready busy f_valid count e_req_valid e_req_ready req_addr e_rsp_valid e_rsp_ready w_addr w_data result_valid result_ready result_flat result_id result_beat done error_code flush_required release_valid w_release_ready'
                dump='vcd add '+' '.join('/'+top+'/'+x for x in signals.split())
                if top=='tb_ecg_feature_core':dump+='; vcd add /tb_ecg_feature_core/dut/state /tb_ecg_feature_core/dut/job'
                macro.write_text(f'onerror {{quit -code 1}}; vcd file {{{wave.as_posix()}}}; {dump}; run -all; vcd flush; quit -code 0\n',encoding='ascii')
                outcomes.append(run(name,[exe('vsim'),'-c','-onfinish','stop','-voptargs=+acc','-wlf',build/(name+'.wlf'),*params,'work.'+top,'-do',f'do {{{macro.as_posix()}}}'],'PASS FEATURE_MATH' if top=='tb_ecg_feature_math' else 'PASS FEATURE_CORE'))
                checks.append(dict(name=name+'_vcd',status='PASS' if wave.is_file() and wave.stat().st_size>100 else 'FAIL',file=wave.relative_to(ROOT).as_posix(),bytes=wave.stat().st_size if wave.exists() else 0))
            success=all(outcomes)
    elif generated and unit:checks.append(dict(name='questa',status='NOT RUN',reason='Required Questa executables unavailable'))
    ver=shutil.which('verilator') or shutil.which('verilator.exe')
    if ver:run('verilator_lint',[ver,'--lint-only','--Wall','--top-module','ecg_feature_core',*rtl])
    else:checks.append(dict(name='verilator_lint',status='NOT RUN',reason='Executable not found on PATH; no installation'))
    prior=None
    if success and args.prior_regression:
        before=set((ROOT/'build/phase3b').glob('*/results.json'))
        ok=run('prior_regressions',[python,'-B',ROOT/'tools/run_ecg_window_tests.py','--questa-dir',args.questa_dir],'PASS Phase 3B:',cwd=ROOT,composite=True,timeout=1200)
        after=set((ROOT/'build/phase3b').glob('*/results.json'))-before
        if ok and len(after)==1:
            prior=after.pop().relative_to(ROOT).as_posix();old=json.loads((ROOT/prior).read_text())
            ok=old['status']=='PASS' and not any(c['status']=='FAIL' and not c.get('expected_baseline_failure') for c in old['checks'])
        else:ok=False
        checks.append(dict(name='prior_regression_summary',status='PASS' if ok else 'FAIL'))
    else:checks.append(dict(name='prior_regressions',status='NOT RUN',reason='Explicit --prior-regression after new tests pass; previous source files unchanged'))
    checks.append(dict(name='sources_unchanged_during_run',status='PASS' if all(h(ROOT/n)==v for n,v in hashes.items()) else 'FAIL'))
    vectors={x.relative_to(ROOT).as_posix():h(x) for x in (build/'vectors').glob('*') if x.is_file()}
    status='FAIL' if any(x['status']=='FAIL' for x in checks) else ('PASS' if success else 'NOT RUN')
    result=dict(status=status,checks=checks,source_sha256=hashes,vector_sha256=vectors,build_directory=build.relative_to(ROOT).as_posix(),prior_regression=prior,training_preprocessing_parity='NOT RUN',hardware_synthesis_timing='NOT RUN')
    text=json.dumps(result,indent=2)+'\n';(build/'results.json').write_text(text,encoding='utf-8')
    summary=ROOT/'docs/phase3c_results.json'
    if summary.exists():summary=ROOT/'docs'/('phase3c_results_'+build.name+'.json')
    with summary.open('x',encoding='utf-8') as out:out.write(text)
    print(status,'Phase3C',build,flush=True)
    return 0 if status=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
