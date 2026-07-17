import os, sys, json

f1 = r'C:\Users\aaron\.qoder\cache\projects\QuantDinger-345186c9\agent-tools\62ae1e21\6abe55ad.txt'
f2 = r'C:\Users\aaron\.qoder\cache\projects\QuantDinger-345186c9\agent-tools\62ae1e21\88cc0582.txt'
out = r'd:\aaron\miniso\QuantDinger\_analysis_output.txt'

# Debug
sys.stderr.write(f"f1 exists: {os.path.exists(f1)}\n")
sys.stderr.write(f"f2 exists: {os.path.exists(f2)}\n")
sys.stderr.write(f"f1 size: {os.path.getsize(f1)}\n")
sys.stderr.write(f"f2 size: {os.path.getsize(f2)}\n")

with open(out, 'w', encoding='utf-8') as out_f:
    try:
        with open(f1, 'r', encoding='utf-8') as f:
            data_1d = json.load(f)
        out_f.write(f"1D loaded OK, keys: {list(data_1d.keys())[:5]}\n")
        
        r1d = data_1d.get('job', data_1d).get('result', {})
        trades_1d = r1d.get('trades', [])
        out_f.write(f"1D trades: {len(trades_1d)}\n")
        
        with open(f2, 'r', encoding='utf-8') as f:
            data_4h = json.load(f)
        
        r4h = data_4h.get('job', data_4h).get('result', {})
        trades_4h = r4h.get('trades', [])
        out_f.write(f"4H trades: {len(trades_4h)}\n")
        out_f.write(f"1D result keys: {list(r1d.keys())[:10]}\n")
        out_f.write(f"4H result keys: {list(r4h.keys())[:10]}\n")
        
    except Exception as e:
        import traceback
        out_f.write(f"ERROR: {e}\n")
        out_f.write(traceback.format_exc())
