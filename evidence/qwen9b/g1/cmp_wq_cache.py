import pickle, sys, numpy as np
def load(p):
    with open(p,'rb') as f: return pickle.load(f)
a=load(sys.argv[1]); b=load(sys.argv[2])
ka, kb = a["key"], b["key"]
diff={k:(ka.get(k),kb.get(k)) for k in set(ka)|set(kb) if ka.get(k)!=kb.get(k)}
print("key fields that differ:", diff)
def walk(x,y,path="q"):
    if isinstance(x,dict):
        assert sorted(x)==sorted(y), (path, sorted(x), sorted(y))
        for k in sorted(x):
            yield from walk(x[k],y[k],f"{path}.{k}")
    elif isinstance(x,(list,tuple)):
        assert len(x)==len(y), (path,len(x),len(y))
        for i,(u,v) in enumerate(zip(x,y)): yield from walk(u,v,f"{path}[{i}]")
    elif isinstance(x,np.ndarray) or isinstance(y,np.ndarray):
        u,v=np.asarray(x),np.asarray(y)
        yield (path, u.dtype==v.dtype and u.shape==v.shape and np.array_equal(u,v), u.size)
    else:
        yield (path, x==y, 1)
n=0; bad=[]; elems=0
for path,same,size in walk(a["payload"],b["payload"]):
    n+=1; elems+=size
    if not same: bad.append(path)
print(f"compared {n} leaves / {elems} elements; MISMATCHES: {len(bad)}")
if bad: print("first 10:", bad[:10])
print("VERDICT:", "BYTE-IDENTICAL CONTENT" if not bad else "CONTENT DIFFERS")
