import sys, json
sys.path.insert(0, '/home/claude/backend')
from generator2 import CrosswordGenerator

def compact_search(entries, seed_base, tries_per_seed=25, n_seeds=20):
    best = None
    best_key = None
    for i in range(n_seeds):
        seed = seed_base * 1000 + i
        gen = CrosswordGenerator(entries, seed=seed)
        gen.generate(tries=tries_per_seed)
        if gen.unplaced:
            continue
        key = (max(gen.n_cols, gen.n_rows), gen.n_cols * gen.n_rows)
        if best_key is None or key < best_key:
            best_key = key
            best = gen
    return best

def process_topic(all_data, name, clues_file, groups_file, seed_base):
    clues = json.load(open(clues_file))
    groups = json.load(open(groups_file))
    for gnum_str, words in groups.items():
        gnum = int(gnum_str)
        entries = [(w, clues[w]) for w in words]
        gen = compact_search(entries, seed_base + gnum)
        title = f"{name} #{gnum}"
        all_data[title] = {
            "grid_w": gen.n_cols, "grid_h": gen.n_rows,
            "grid": {f"{r},{c}": ch for (r, c), ch in gen.grid.items()},
            "placed": gen.placed,
        }
        print(f"{title}: {gen.n_cols}x{gen.n_rows}, placed={len(gen.placed)}")
