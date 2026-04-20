import json, pathlib
p = pathlib.Path(__file__).parent / '_patches.json'
patches = json.loads(p.read_text(encoding='utf-8'))

new_patches = [
    [
        'className:"grid grid-cols-3 gap-1.5 p-3",children:[i.jsx(fn,{label:"Tardiness",value:be.totalTardiness',
        'className:"grid grid-cols-4 gap-1.5 p-3",children:[i.jsx(fn,{label:"Tardiness",value:be.totalTardiness',
    ],
    [
        'Completed",value:be.completedJobs??0,color:"text-slate-700"})]',
        'Completed",value:be.completedJobs??0,color:"text-slate-700"}),i.jsx(fn,{label:"Jobs/hr",value:be.jobsPerHour??0,color:"text-slate-700",dp:1})]',
    ],
    [
        'className:"grid grid-cols-3 gap-1.5 p-3",children:[i.jsx(fn,{label:"Tardiness",value:Ee.totalTardiness',
        'className:"grid grid-cols-4 gap-1.5 p-3",children:[i.jsx(fn,{label:"Tardiness",value:Ee.totalTardiness',
    ],
    [
        'Completed",value:Ee.completedJobs??0,color:"text-primary"})]',
        'Completed",value:Ee.completedJobs??0,color:"text-primary"}),i.jsx(fn,{label:"Jobs/hr",value:Ee.jobsPerHour??0,color:"text-primary",dp:1})]',
    ],
    [
        'Completed jobs",baseVal:Qe.completedJobs??0,dahsVal:un.completedJobs??0,lowerIsBetter:!1,baseLabel:nt})]',
        'Completed jobs",baseVal:Qe.completedJobs??0,dahsVal:un.completedJobs??0,lowerIsBetter:!1,baseLabel:nt}),i.jsx(ol,{label:"Jobs / hour",baseVal:Qe.jobsPerHour??0,dahsVal:un.jobsPerHour??0,lowerIsBetter:!1,baseLabel:nt})]',
    ],
]
# Append only if not already present
existing = {tuple(x) for x in patches}
added = 0
for np in new_patches:
    if tuple(np) not in existing:
        patches.append(np)
        added += 1
p.write_text(json.dumps(patches, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Added {added} new patches. Total: {len(patches)}')
