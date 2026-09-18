/* ------------------------------------------------------------------
   등가면(isosurface) — 서버가 저장한 궤도 ψ / 전자밀도 ρ 격자(float16 base64)에서
   marching tetrahedra 로 삼각형 메시를 만든다. 결과 화면·오비탈 비교의 3D 뷰어가
   논문 그림처럼 매끈한 lobe(+ 붉은색 · − 파란색)를 그리는 데 쓴다.

     window.rbIso.decode(grid)            → Float32Array (격자 값, C 순서)
     window.rbIso.mesh(grid, iso, sign)   → {pos, nrm, n}  (삼각형 n개 · 꼭짓점 3n · Å 좌표)
     window.rbIso.gradientAt(grid, x,y,z) → 법선 계산용 (내부)

   테이블 없는 marching tetrahedra 를 쓴다 — 정육면체를 여섯 사면체로 나누고, 사면체마다
   등가면이 지나는 변을 선형보간한다. 법선은 격자 값의 기울기(중앙차분)에서 얻어 매끈하게
   음영을 넣는다(양의 lobe 는 −∇ψ, 음의 lobe 는 +∇ψ 가 바깥 방향).
   ------------------------------------------------------------------ */
(function () {
  function f16(h) {
    const s = (h & 0x8000) ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
    if (e === 0) return s * Math.pow(2, -14) * (f / 1024);
    if (e === 31) return f ? NaN : s * Infinity;
    return s * Math.pow(2, e - 15) * (1 + f / 1024);
  }
  function decode(g) {
    if (g._f32) return g._f32;
    const bin = atob(g.data), n = bin.length >> 1, out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = f16(bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8));   // little-endian
    g._f32 = out;
    return out;
  }
  // 정육면체 꼭짓점 8개 (ix,iy,iz 오프셋) 와 여섯 사면체 분할 (대각선 0–6 공유)
  const CORNERS = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  const TETS = [[0, 5, 1, 6], [0, 1, 2, 6], [0, 2, 3, 6], [0, 3, 7, 6], [0, 7, 4, 6], [0, 4, 5, 6]];

  function mesh(g, iso, sign) {
    sign = sign || 1;
    const key = sign + ":" + iso;
    g._meshes = g._meshes || {};
    if (g._meshes[key]) return g._meshes[key];
    const F = decode(g), [nx, ny, nz] = g.shape, [sx, sy, sz] = g.spacing, [ox, oy, oz] = g.origin;
    const at = (ix, iy, iz) => sign * F[(ix * ny + iy) * nz + iz];
    // 격자 노드의 기울기 (중앙차분, 경계는 편차분) — 바깥 방향 법선 = −∇(sign·f)
    const grad = (ix, iy, iz, out) => {
      const x0 = ix > 0 ? ix - 1 : ix, x1 = ix < nx - 1 ? ix + 1 : ix;
      const y0 = iy > 0 ? iy - 1 : iy, y1 = iy < ny - 1 ? iy + 1 : iy;
      const z0 = iz > 0 ? iz - 1 : iz, z1 = iz < nz - 1 ? iz + 1 : iz;
      out[0] = (at(x1, iy, iz) - at(x0, iy, iz)) / ((x1 - x0) * sx || 1);
      out[1] = (at(ix, y1, iz) - at(ix, y0, iz)) / ((y1 - y0) * sy || 1);
      out[2] = (at(ix, iy, z1) - at(ix, iy, z0)) / ((z1 - z0) * sz || 1);
    };
    const pos = [], nrm = [];
    const cv = new Float64Array(8), cx = new Int32Array(8), cy = new Int32Array(8), cz = new Int32Array(8);
    const ga = [0, 0, 0], gb = [0, 0, 0];
    // 변 (a,b) 위 등가면 교점 — 위치와 법선을 보간해 push
    const edge = (a, b) => {
      const va = cv[a], vb = cv[b], t = (vb - va) !== 0 ? (iso - va) / (vb - va) : 0.5;
      pos.push(ox + (cx[a] + (cx[b] - cx[a]) * t) * sx, oy + (cy[a] + (cy[b] - cy[a]) * t) * sy, oz + (cz[a] + (cz[b] - cz[a]) * t) * sz);
      grad(cx[a], cy[a], cz[a], ga); grad(cx[b], cy[b], cz[b], gb);
      let x = -(ga[0] + (gb[0] - ga[0]) * t), y = -(ga[1] + (gb[1] - ga[1]) * t), z = -(ga[2] + (gb[2] - ga[2]) * t);
      const L = Math.hypot(x, y, z) || 1; nrm.push(x / L, y / L, z / L);
    };
    for (let ix = 0; ix < nx - 1; ix++) for (let iy = 0; iy < ny - 1; iy++) for (let iz = 0; iz < nz - 1; iz++) {
      let lo = Infinity, hi = -Infinity;
      for (let c = 0; c < 8; c++) { cx[c] = ix + CORNERS[c][0]; cy[c] = iy + CORNERS[c][1]; cz[c] = iz + CORNERS[c][2]; const v = at(cx[c], cy[c], cz[c]); cv[c] = v; if (v < lo) lo = v; if (v > hi) hi = v; }
      if (lo >= iso || hi < iso) continue;                     // 등가면이 이 칸을 지나지 않음
      for (const t of TETS) {
        const inside = [], outside = [];
        for (const c of t) (cv[c] >= iso ? inside : outside).push(c);
        if (inside.length === 0 || inside.length === 4) continue;
        if (inside.length === 1) { const a = inside[0]; edge(a, outside[0]); edge(a, outside[1]); edge(a, outside[2]); }
        else if (inside.length === 3) { const d = outside[0]; edge(inside[0], d); edge(inside[1], d); edge(inside[2], d); }
        else { const [a, b] = inside, [c, d] = outside; edge(a, c); edge(a, d); edge(b, d); edge(a, c); edge(b, d); edge(b, c); }
      }
    }
    const out = {pos: new Float32Array(pos), nrm: new Float32Array(nrm), n: pos.length / 9};
    const keys = Object.keys(g._meshes); if (keys.length > 6) delete g._meshes[keys[0]];   // 캐시 상한
    g._meshes[key] = out;
    return out;
  }
  window.rbIso = {decode, mesh};
})();
