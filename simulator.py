"""Cycle-level Tomasulo model with an in-order issue bundle and retirement.
The supplied single-issue starter is retained verbatim under ../original/.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import re

OPS={'ld','sd','add','addi','sub','add.d','sub.d','mult.d','beq','bne'}
BRANCH={'beq','bne'}
@dataclass
class Hardware:
    rs: dict = field(default_factory=lambda:dict(integer=4,fp_add=3,fp_mul=2,ls=5))
    latency: dict = field(default_factory=lambda:dict(integer=1,fp_add=4,fp_mul=15,ls=1))
    units: dict = field(default_factory=lambda:dict(integer=1,fp_add=1,fp_mul=1,ls=1))
    branch_offsets: str = "words"
    memory_cycles: int = 5
    rob_entries: int = 64
    issue_width: int = 1
    writeback_width: int = 1
    commit_width: int = 1

@dataclass
class Instruction:
    text: str
    op: str
    dest: str|None
    sources: list
    immediate: int = 0
    kind: str = 'integer'

@dataclass
class Record:
    tag: int
    pc: int
    ins: Instruction
    operands: list
    issue: int
    ex: list = field(default_factory=list)
    mem: list = field(default_factory=list)
    wb: int|None = None
    commit: int|None = None
    squashed: bool = False
    ready: bool = False
    result: float|int|None = None
    address: int|None = None
    finish: int|None = None
    predicted: int|None = None


def reg(name):
    name=name.upper()
    if not re.fullmatch(r'[RF](?:[0-9]|[12][0-9]|3[01])',name):
        raise ValueError('Invalid register '+name)
    return name

def decode(line):
    # Permit comma-separated ISA syntax and the starter's whitespace-only syntax.
    bits=line.replace(',',' ').split();op=bits[0].lower()
    if op not in OPS:raise ValueError('Unsupported opcode '+op)
    if op in {'ld','sd'}:
        if len(bits)!=3:raise ValueError('Expected load/store operand and offset(base)')
        m=re.fullmatch(r'(-?\d+)\(([rR]\d+)\)',bits[2])
        if not m:raise ValueError('Invalid memory operand '+bits[2])
        dest=reg(bits[1]);base=reg(m[2])
        if not dest.startswith('F'):raise ValueError('Load/store operand must be FP register')
        return Instruction(line,op,dest if op=='ld' else None,
                           [base] if op=='ld' else [base,dest],int(m[1]),'ls')
    if len(bits)!=4:raise ValueError('Expected three operands: '+line)
    if op in BRANCH:return Instruction(line,op,None,[reg(bits[1]),reg(bits[2])],int(bits[3]))
    dest=reg(bits[1]);a=reg(bits[2])
    sources=[a] if op=='addi' else [a,reg(bits[3])]
    expected='F' if '.' in op else 'R'
    if any(not x.startswith(expected) for x in [dest]+sources):raise ValueError('Wrong register class: '+line)
    kind='fp_mul' if op=='mult.d' else ('fp_add' if '.' in op else 'integer')
    return Instruction(line,op,dest,sources,int(bits[3]) if op=='addi' else 0,kind)


def read_program(path):
    hw=Hardware();regs={f'{k}{i}':0 for k in 'RF' for i in range(32)};memory={}
    program=[];explicit=set()
    labels={'integer adder':'integer','fp adder':'fp_add','fp multiplier':'fp_mul','load/store unit':'ls'}
    for num,raw in enumerate(Path(path).read_text().splitlines(),1):
        line=raw.split('#',1)[0].strip()
        if not line:continue
        low=line.lower()
        try:
            found=False
            for label,kind in labels.items():
                if low.startswith(label):
                    values=[int(x) for x in line[len(label):].split()]
                    if kind=='ls':
                        if len(values)!=4:raise ValueError('Load/store row needs RS, EX, MEM, FUs')
                        hw.rs[kind],hw.latency[kind],hw.memory_cycles,hw.units[kind]=values
                    else:
                        if len(values)!=3:raise ValueError('FU row needs RS, EX, FUs')
                        hw.rs[kind],hw.latency[kind],hw.units[kind]=values
                    found=True;break
            if found:continue
            if low.startswith('branch offsets'):
                hw.branch_offsets=line.split('=',1)[1].strip().lower()
                if hw.branch_offsets not in {'bytes','words'}:raise ValueError('Branch offsets must be bytes or words')
                continue
            m=re.fullmatch(r'(ROB entries|Issue width|Writeback width|Commit width)\s*=\s*(\d+)',line,re.I)
            if m:
                key={'rob entries':'rob_entries','issue width':'issue_width','writeback width':'writeback_width','commit width':'commit_width'}[m[1].lower()]
                setattr(hw,key,int(m[2]));explicit.add(key);continue
            if re.match(r'(?:[RF]\d+|Mem\[\d+\])\s*=',line,re.I):
                for assignment in line.split(','):
                    m=re.fullmatch(r'\s*([RF]\d+|Mem\[(\d+)\])\s*=\s*([-+\d.eE]+)\s*',assignment,re.I)
                    if not m:raise ValueError('Invalid initialization '+assignment)
                    v=float(m[3]);v=int(v) if v.is_integer() else v
                    if m[2] is not None:
                        address=int(m[2]);check_address(address);memory[address]=v
                    else:
                        name=reg(m[1]);regs[name]=v
                continue
            program.append(decode(line))
        except (ValueError,IndexError) as e:raise ValueError(f'{path}:{num}: {e}') from e
    if not 1<=hw.issue_width<=4:raise ValueError('Issue width must be 1 through 4')
    # The single logical CDB remains one-result-per-cycle by default.
    # Optional bandwidth settings support comparison with the sample's wider WB/commit.
    if 'commit_width' not in explicit:hw.commit_width=hw.issue_width
    if any(v<1 for mapping in [hw.rs,hw.latency,hw.units] for v in mapping.values()):raise ValueError('Hardware values must be positive')
    if min(hw.memory_cycles,hw.rob_entries,hw.writeback_width,hw.commit_width)<1:raise ValueError('Hardware values must be positive')
    regs['R0']=0
    return hw,regs,memory,program


def check_address(address):
    if not 0<=address<256:raise ValueError(f'Memory byte address {address} outside 0..255')

class Simulator:
    def __init__(self,hardware,registers,memory,program):
        self.hw=hardware;self.regs=dict(registers);self.memory=dict(memory);self.program=program
        self.rat={};self.rob=[];self.records=[];self.pc=0;self.cycle=0;self.next_tag=1
        self.memory_op=None;self.resume_cycle=0
        self.btb=[None]*8;self.mispredictions=0;self.memory_replays=0
    def target(self,r):
        offset=r.ins.immediate
        if self.hw.branch_offsets=="bytes":
            if offset % 4:raise ValueError("Byte branch offset must be a multiple of four")
            offset//=4
        return r.pc+1+offset
    def operand(self,name):
        if name=='R0':return (None,0)
        tag=self.rat.get(name)
        if tag is not None:
            producer=next(r for r in self.rob if r.tag==tag)
            if producer.wb is not None:return (None,producer.result)
            return (tag,None)
        return (None,self.regs[name])
    def broadcast(self,r):
        r.wb=self.cycle;r.ready=True
        for other in self.rob:
            other.operands=[(None,r.result) if tag==r.tag else (tag,value) for tag,value in other.operands]
    def squash(self,branch,correct,count_branch=True):
        removed=[r for r in self.rob if r.tag>branch.tag]
        for r in removed:r.squashed=True
        self.rob=[r for r in self.rob if r.tag<=branch.tag]
        if self.memory_op and self.memory_op[0].squashed:self.memory_op=None
        self.rat={}
        for r in self.rob:
            if r.ins.dest and r.ins.dest!='R0':self.rat[r.ins.dest]=r.tag
        self.pc=correct;self.resume_cycle=self.cycle+2
        if count_branch:self.mispredictions+=1
        else:self.memory_replays+=1
    def address_ready(self,r):
        if r.ins.op=="sd" and any(x.tag>r.tag and x.ins.op=="ld" and x.mem and x.address==r.address for x in self.rob):
            self.squash(r,r.pc+1,count_branch=False)
    def retirement(self):
        retired=0
        while self.rob and retired<self.hw.commit_width:
            r=self.rob[0]
            if not r.ready:break
            if r.ins.op in {"ld","sd"}:check_address(r.address)
            if r.ins.op=='sd':
                if len(r.mem)==2 and r.mem[1]<self.cycle:pass
                elif not r.mem and self.memory_op is None and r.ex[1]<self.cycle and all(t is None for t,v in r.operands):
                    r.mem=[self.cycle];self.memory_op=(r,self.cycle+self.hw.memory_cycles-1,'store');break
                else:break
            elif r.ins.op in BRANCH:
                if r.ex[1]>=self.cycle:break
            elif r.wb is None or r.wb>=self.cycle:break
            r.commit=self.cycle
            if r.ins.dest and r.ins.dest!='R0':
                self.regs[r.ins.dest]=r.result
                if self.rat.get(r.ins.dest)==r.tag:self.rat.pop(r.ins.dest)
            self.rob.pop(0);retired+=1
        self.regs['R0']=0
    def writeback(self):
        candidates=[r for r in self.rob if r.finish is not None and r.finish<self.cycle and r.wb is None and r.ins.op not in BRANCH|{'sd'}]
        for r in candidates[:self.hw.writeback_width]:self.broadcast(r)
    def memory_stage(self):
        if self.memory_op:
            r,end,kind=self.memory_op
            if end<=self.cycle:
                r.mem.append(self.cycle)
                if kind=='store':self.memory[r.address]=r.operands[1][1]
                else:
                    if kind=='load':r.result=self.memory.get(r.address,0)
                    r.finish=self.cycle
                self.memory_op=None
            # A single-ported nonpipelined memory starts a new operation next cycle.
            return
        for r in self.rob:
            if r.ins.op!='ld' or len(r.ex)!=2 or r.ex[1]>=self.cycle or r.mem:continue
            stores=[s for s in self.rob if s.tag<r.tag and s.ins.op=='sd']
            # Speculate past unknown older addresses; a later alias replays younger work.
            matches=[s for s in stores if s.address==r.address]
            if matches:
                s=matches[-1]
                if s.operands[1][0] is not None:continue
                r.result=s.operands[1][1];duration=1;kind='forward'
            else:duration=self.hw.memory_cycles;kind='load'
            r.mem=[self.cycle]
            self.memory_op=(r,self.cycle+duration-1,kind)
            if duration==1:
                r.mem.append(self.cycle)
                if kind=='load':r.result=self.memory.get(r.address,0)
                r.finish=self.cycle;self.memory_op=None
            break
    def execute(self):
        # Finish older operations first; a branch recovery cancels younger work.
        for r in list(self.rob):
            if r.squashed or len(r.ex)!=1:continue
            if r.ex[0]+self.hw.latency[r.ins.kind]-1>self.cycle:continue
            r.ex.append(self.cycle);op=r.ins.op;v=[x[1] for x in r.operands]
            if op in {'ld','sd'}:
                r.address=int(v[0]+r.ins.immediate);self.address_ready(r)
                if op=='sd':r.ready=True
            elif op in BRANCH:
                taken=(v[0]==v[1]) if op=='beq' else (v[0]!=v[1])
                # PC is internally an instruction index; immediate is a word offset.
                correct=self.target(r) if taken else r.pc+1
                self.btb[r.pc&7]=(r.pc,taken,self.target(r))
                r.ready=True
                if correct!=r.predicted:self.squash(r,correct)
            else:
                r.result=(v[0]+r.ins.immediate if op=='addi' else
                          v[0]-v[1] if op in {'sub','sub.d'} else
                          v[0]*v[1] if op=='mult.d' else v[0]+v[1])
                r.finish=self.cycle
        for kind in self.hw.rs:
            running=[r for r in self.rob if r.ins.kind==kind and len(r.ex)==1]
            # Integer/LS units are unpipelined; FP units accept one start each cycle.
            capacity=self.hw.units[kind]-(len(running) if kind in {'integer','ls'} else 0)
            # A unit completing this cycle is not reused until next cycle.
            if kind in {'integer','ls'}:
                capacity-=sum(r.ins.kind==kind and len(r.ex)==2 and r.ex[1]==self.cycle for r in self.rob)
            ready=[r for r in self.rob if r.ins.kind==kind and not r.ex and r.issue<self.cycle and
                   (r.operands[0][0] is None if r.ins.op=='sd' else all(t is None for t,v in r.operands))]
            for r in ready[:max(0,capacity)]:
                r.ex=[self.cycle]
                # One-cycle operations complete at the end of their start cycle.
                if self.hw.latency[kind]==1:
                    op=r.ins.op;v=[x[1] for x in r.operands];r.ex.append(self.cycle)
                    if op in {'ld','sd'}:
                        r.address=int(v[0]+r.ins.immediate);self.address_ready(r)
                        if op=='sd':r.ready=True
                    elif op in BRANCH:
                        taken=(v[0]==v[1]) if op=='beq' else (v[0]!=v[1])
                        correct=self.target(r) if taken else r.pc+1
                        self.btb[r.pc&7]=(r.pc,taken,self.target(r));r.ready=True
                        if correct!=r.predicted:
                            self.squash(r,correct);break
                    else:
                        r.result=(v[0]+r.ins.immediate if op=='addi' else v[0]-v[1] if op in {'sub','sub.d'} else v[0]*v[1] if op=='mult.d' else v[0]+v[1]);r.finish=self.cycle
    def issue(self):
        if self.cycle<self.resume_cycle:return
        for _ in range(self.hw.issue_width):
            if not 0<=self.pc<len(self.program):break
            ins=self.program[self.pc]
            if len(self.rob)>=self.hw.rob_entries:break
            # LS queue frees a completed load at MEM completion; stores at retirement.
            if ins.kind=='ls':used=sum(r.ins.kind=='ls' and (r.ins.op=='sd' or len(r.mem)<2) for r in self.rob)
            else:used=sum(r.ins.kind==ins.kind and (r.ex==[] or (r.ins.op not in BRANCH and r.wb is None)) for r in self.rob)
            if used>=self.hw.rs[ins.kind]:break # stop the bundle; never bypass a stalled instruction
            r=Record(self.next_tag,self.pc,ins,[self.operand(x) for x in ins.sources],self.cycle)
            self.next_tag+=1;self.rob.append(r);self.records.append(r)
            if ins.dest and ins.dest!='R0':self.rat[ins.dest]=r.tag
            self.pc+=1
            if ins.op in BRANCH:
                old=self.btb[r.pc&7]
                r.predicted=old[2] if old and old[0]==r.pc and old[1] else r.pc+1
                self.pc=r.predicted
                # Sequential issue bundle terminates at a control transfer.
                break
    def run(self,max_cycles=100000):
        while self.rob or 0<=self.pc<len(self.program):
            self.cycle+=1
            if self.cycle>max_cycles:raise RuntimeError('Cycle limit exceeded (possible infinite loop or deadlock)')
            self.retirement();self.writeback();self.memory_stage();self.execute();self.issue()
        return self
    def to_dict(self):
        return dict(cycles=self.cycle,hardware=asdict(self.hw),registers=self.regs,memory=self.memory,
                    mispredictions=self.mispredictions,memory_replays=self.memory_replays,records=[asdict(r) for r in self.records])
    def report(self):
        rows=['INSTRUCTION STATUS','ID PC Instruction                     ISSUE EX       MEM      WB COMMIT STATUS']
        for r in self.records:
            rows.append(f'{r.tag:2} {r.pc*4:3} {r.ins.text:30} {r.issue:5} {str(r.ex):8} {str(r.mem):8} {str(r.wb):3} {str(r.commit):6} '+('SQUASHED' if r.squashed else 'COMMITTED'))
        rows+=['','REGISTER VALUES']
        for k in 'RF':
            rows.append(' '.join(f'{k}{i}={self.regs[k+str(i)]:g}' for i in range(32)))
        rows+=['','NON-ZERO MEMORY VALUES','Addresses Values']
        rows += [f'{a:3} {v:g}' for a,v in sorted(self.memory.items()) if v!=0]
        rows += ['',f'Total cycles: {self.cycle}',f'Branch mispredictions: {self.mispredictions}',f'Memory dependence replays: {self.memory_replays}']
        return '\n'.join(rows)+'\n'
