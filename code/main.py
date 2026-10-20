#!/usr/bin/env python3
"""Run from any directory: python3 code/main.py tests/arithmetic.in --issue-width 4."""
import argparse,json
from pathlib import Path
from simulator import read_program,Simulator

def main():
    p=argparse.ArgumentParser(description='Tomasulo multi issue simulator')
    p.add_argument('input',nargs='?',default=str(Path(__file__).with_name('code.in')))
    p.add_argument('--issue-width',type=int,choices=range(1,5))
    p.add_argument('--json',type=Path)
    p.add_argument('--max-cycles',type=int,default=100000)
    a=p.parse_args();hw,regs,mem,program=read_program(a.input)
    if a.issue_width is not None:
        hw.issue_width=a.issue_width;hw.commit_width=a.issue_width
    sim=Simulator(hw,regs,mem,program).run(a.max_cycles)
    print(sim.report(),end='')
    if a.json:a.json.write_text(json.dumps(sim.to_dict(),indent=2)+'\n')
if __name__=='__main__':main()
