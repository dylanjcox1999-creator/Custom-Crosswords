import random

class CrosswordGenerator:
    def __init__(self, words_clues, seed=0):
        self.entries_master = sorted(words_clues, key=lambda x: -len(x[0]))
        self.seed = seed

    def _can_place(self, grid, word, row, col, direction, used_starts=None):
        n = len(word)
        for i in range(n):
            r, c = (row, col+i) if direction == 'A' else (row+i, col)
            if (r, c) in grid:
                if grid[(r, c)] != word[i]:
                    return False
            else:
                if direction == 'A':
                    if (r-1, c) in grid or (r+1, c) in grid:
                        return False
                else:
                    if (r, c-1) in grid or (r, c+1) in grid:
                        return False
        if direction == 'A':
            before, after = (row, col-1), (row, col+n)
        else:
            before, after = (row-1, col), (row+n, col)
        if before in grid or after in grid:
            return False
        # reject if another word already starts at this exact cell in the same
        # direction (can happen when one word is a prefix of another)
        if used_starts is not None and (row, col, direction) in used_starts:
            return False
        return True

    def _bbox_with(self, grid, word, row, col, direction):
        rs = [r for r, c in grid.keys()]
        cs = [c for r, c in grid.keys()]
        n = len(word)
        for i in range(n):
            r, c = (row, col+i) if direction == 'A' else (row+i, col)
            rs.append(r); cs.append(c)
        return (max(rs)-min(rs)+1) * (max(cs)-min(cs)+1)

    def _find_best(self, grid, word, used_starts=None):
        best = None
        best_key = None  # (-intersections, bbox_area)
        for (r, c), letter in list(grid.items()):
            for i, ch in enumerate(word):
                if ch != letter:
                    continue
                for direction, row, col in [('A', r, c - i), ('D', r - i, c)]:
                    if self._can_place(grid, word, row, col, direction, used_starts):
                        intersections = 0
                        for k in range(len(word)):
                            cell = (row, col+k) if direction == 'A' else (row+k, col)
                            if cell in grid:
                                intersections += 1
                        area = self._bbox_with(grid, word, row, col, direction)
                        key = (-intersections, area)
                        if best_key is None or key < best_key:
                            best_key = key
                            best = (row, col, direction)
        return best

    def _attempt(self, entries):
        grid = {}
        placed = []
        used_starts = set()
        first_word, first_clue = entries[0]
        for i, ch in enumerate(first_word):
            grid[(0, i)] = ch
        placed.append({'word': first_word, 'clue': first_clue, 'row': 0, 'col': 0, 'dir': 'A'})
        used_starts.add((0, 0, 'A'))
        remaining = list(entries[1:])
        guard = 0
        while remaining and guard < 400:
            guard += 1
            progressed = False
            # try remaining words in current order, place first one with any valid spot
            for idx, (word, clue) in enumerate(remaining):
                spot = self._find_best(grid, word, used_starts)
                if spot:
                    row, col, direction = spot
                    for i, ch in enumerate(word):
                        r, c = (row, col+i) if direction == 'A' else (row+i, col)
                        grid[(r, c)] = ch
                    placed.append({'word': word, 'clue': clue, 'row': row, 'col': col, 'dir': direction})
                    used_starts.add((row, col, direction))
                    remaining.pop(idx)
                    progressed = True
                    break
            if not progressed:
                break
        return grid, placed, remaining

    def generate(self, tries=60):
        best_result = None
        best_score = None
        for t in range(tries):
            rnd = random.Random(self.seed * 1000 + t)
            entries = list(self.entries_master)
            rest = entries[1:]
            rnd.shuffle(rest)
            entries = [entries[0]] + rest
            grid, placed, unplaced = self._attempt(entries)
            rs = [r for r, c in grid.keys()]
            cs = [c for r, c in grid.keys()]
            area = (max(rs)-min(rs)+1) * (max(cs)-min(cs)+1) if grid else 999999
            # prefer: fewest unplaced, then smallest bbox area, then most intersecting (fewer total cells relative to letters)
            score = (len(unplaced), area)
            if best_score is None or score < best_score:
                best_score = score
                best_result = (grid, placed, unplaced)
        self.grid, self.placed, self.unplaced = best_result
        self._normalize()
        self._number()

    def _normalize(self):
        rows = [r for r, c in self.grid.keys()]
        cols = [c for r, c in self.grid.keys()]
        min_r, min_c = min(rows), min(cols)
        new_grid = {}
        for (r, c), ch in self.grid.items():
            new_grid[(r - min_r, c - min_c)] = ch
        self.grid = new_grid
        for p in self.placed:
            p['row'] -= min_r
            p['col'] -= min_c
        self.n_rows = max(r for r, c in self.grid.keys()) + 1
        self.n_cols = max(c for r, c in self.grid.keys()) + 1

    def _number(self):
        starts = sorted(set((p['row'], p['col']) for p in self.placed))
        num_map = {cell: i+1 for i, cell in enumerate(starts)}
        for p in self.placed:
            p['num'] = num_map[(p['row'], p['col'])]
