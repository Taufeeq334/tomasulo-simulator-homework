#!/usr/bin/env python3
"""Compare all committed architectural results with an independent ISA interpreter."""
from pathlib import Path
import sys,json,csv,math,subprocess,copy
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'code'))
from simulator import read_program,Simulator

def reference(hw,regs,mem,program):
    regs=dict(regs);mem=dict(mem);pc=0;steps=0
    while 0<=pc<len(program):
        ins=program[pc];op=ins.op;v=[regs[n] for n in ins.sources];nxt=pc+1
        if op in {'beq','bne'}:
            take=v[0]==v[1] if op=='beq' else v[0]!=v[1]
            if take:nxt=pc+1+(ins.immediate//4 if hw.branch_offsets=='bytes' else ins.immediate)
        elif op=='ld':regs[ins.dest]=mem.get(int(v[0]+ins.immediate),0)
        elif op=='sd':mem[int(v[0]+ins.immediate)]=v[1]
        else:
            value=v[0]+ins.immediate if op=='addi' else v[0]-v[1] if op in {'sub','sub.d'} else v[0]*v[1] if op=='mult.d' else v[0]+v[1]
            if ins.dest!='R0':regs[ins.dest]=value
        regs['R0']=0;pc=nxt;steps+=1
        if steps>10000:raise AssertionError('Reference cycle limit')
    return regs,mem

def verify_schedule(sim):
    issued={};writes={};commits={}
    for r in sim.records:
        issued[r.issue]=issued.get(r.issue,0)+1
        if r.squashed:assert r.commit is None;continue
        assert r.commit is not None
        assert r.issue<r.ex[0]<=r.ex[1]<r.commit
        commits[r.commit]=commits.get(r.commit,0)+1
        if r.wb is not None:
            assert (r.mem[-1] if r.ins.op=='ld' else r.ex[-1])<r.wb<r.commit
            writes[r.wb]=writes.get(r.wb,0)+1
    assert max(issued.values(),default=0)<=sim.hw.issue_width
    assert max(writes.values(),default=0)<=sim.hw.writeback_width
    assert max(commits.values(),default=0)<=sim.hw.commit_width
    retired=[r.tag for r in sim.records if r.commit is not None]
    assert [r.tag for r in sorted((r for r in sim.records if r.commit is not None),key=lambda r:(r.commit,r.tag))]==sorted(retired)
    # Unit launch bandwidth and nonpipelined integer/LS exclusion.
    for kind in sim.hw.rs:
        starts={}
        finished=[]
        for r in sim.records:
            if r.squashed or r.ins.kind!=kind or not r.ex:continue
            starts[r.ex[0]]=starts.get(r.ex[0],0)+1
            finished.append(r)
        assert max(starts.values(),default=0)<=sim.hw.units[kind]
        if kind in {'integer','ls'}:
            for cycle in range(1,sim.cycle+1):
                assert sum(r.ex[0]<=cycle<=r.ex[1] for r in finished)<=sim.hw.units[kind]
    for r in sim.records:
        if r.ins.op in {'beq','bne'} and not r.squashed:
            a,b=[v for tag,v in r.operands]
            taken=(a==b) if r.ins.op=='beq' else (a!=b)
            correct=sim.target(r) if taken else r.pc+1
            if correct!=r.predicted:
                assert not any(x.issue in {r.ex[1],r.ex[1]+1} for x in sim.records)


def main():
    out=root/'results';out.mkdir(exist_ok=True);rows=[]
    for path in sorted((root/'tests').glob('*.in')):
        hw,regs,mem,prog=read_program(path);expected=reference(hw,regs,mem,prog)
        for width in range(1,5):
            h=copy.deepcopy(hw);h.issue_width=h.commit_width=width
            sim=Simulator(h,regs,mem,prog).run();verify_schedule(sim)
            assert all(math.isclose(sim.regs[k],v,rel_tol=1e-12,abs_tol=1e-12) for k,v in expected[0].items()),(path,width,'registers',sim.regs,expected[0])
            assert {k:v for k,v in sim.memory.items() if v}=={k:v for k,v in expected[1].items() if v},(path,width,'memory')
            (out/f'{path.stem}_w{width}.txt').write_text(sim.report())
            (out/f'{path.stem}_w{width}.json').write_text(json.dumps(sim.to_dict(),indent=2)+'\n')
            rows.append([path.stem,width,sim.cycle,sum(r.commit is not None for r in sim.records),sim.mispredictions,'PASS'])
    with (out/'summary.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['test','issue_width','cycles','committed','mispredictions','architecture_check']);w.writerows(rows)
    # Exercise the public CLI independently of direct class tests.
    p=subprocess.run([sys.executable,str(root/'code/main.py'),str(root/'tests/arithmetic.in'),'--issue-width','4'],capture_output=True,text=True,check=True)
    assert 'REGISTER VALUES' in p.stdout and 'NON-ZERO MEMORY VALUES' in p.stdout
    # Width omission defaults to 1; invalid width rejects input.
    assert read_program(root/'tests/loop.in')[0].issue_width==1
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        bad=Path(td)/'bad.in';bad.write_text('Issue width = 5\nAddi R1 R0 1\n')
        try:read_program(bad)
        except ValueError:pass
        else:raise AssertionError('Invalid width accepted')
    # A load must actually speculate past an unresolved alias and be replayed.
    h,r,m,p=read_program(root/'tests/memory_replay.in');h.issue_width=h.commit_width=4
    sim=Simulator(h,r,m,p).run()
    assert sim.memory_replays>=1 and sim.regs['F2']==7 and sim.regs['F3']==14
    # Wrong-path out-of-range accesses must be discarded without an architectural fault.
    h,r,m,p=read_program(root/'tests/wrong_path_fault.in');h.issue_width=h.commit_width=4
    assert Simulator(h,r,m,p).run().regs['R1']==9
    # Deterministic randomized arithmetic/dependency stress, 50 programs x 4 widths.
    import random
    for seed in range(50):
        rng=random.Random(seed)
        from simulator import Hardware,decode
        h=Hardware();h.rob_entries=3+seed%9;h.rs['integer']=1+seed%4
        h.units['integer']=1+seed%2;h.latency['integer']=1+seed%3
        regs={f'{k}{i}':0 for k in 'RF' for i in range(32)}
        prog=[decode(f'Addi R{i}, R0, {i}') for i in range(1,9)]
        for _ in range(40):
            dest=rng.randrange(9);a=rng.randrange(9);b=rng.randrange(9)
            prog.append(decode(f'{rng.choice(["Add","Sub"])} R{dest}, R{a}, R{b}'))
        expected=reference(h,regs,{},prog)
        for width in range(1,5):
            h.issue_width=h.commit_width=width
            sim=Simulator(copy.deepcopy(h),regs,{},prog).run();verify_schedule(sim)
            assert sim.regs==expected[0],(seed,width)
    (out/'verification.txt').write_text(f'{len(rows)} test/width combinations PASS against sequential architectural reference.\nStage ordering, issue/writeback/commit bandwidth, FU launch/occupancy, branch recovery gaps and retirement order assertions PASS.\n200 deterministic randomized dependency runs PASS against reference.\nCLI smoke check PASS; default width 1 and invalid-width rejection PASS.\n')
    print((out/'verification.txt').read_text(),end='')
if __name__=='__main__':main()
