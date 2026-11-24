import { Panel, RepoChip, SectionTitle } from "../components/ui";
import { repos } from "../data/repos";

export function LandscapeTab() {
  return (
    <div className="space-y-10">
      <SectionTitle eyebrow="02 / The landscape" title="Five neighbours, each with one idea worth stealing">
        I searched for comparable open-source personal agents, cloned the ones that matter, and read the specific files behind each project's
        signature idea. The goal was not to bolt five repos together. It was to find the one mechanism each does best.
      </SectionTitle>

      <div className="space-y-4">
        {repos.map((r) => (
          <Panel key={r.key} className="overflow-hidden">
            <div className="grid gap-0 lg:grid-cols-[320px_1fr]">
              <div className="border-b border-line p-5 lg:border-b-0 lg:border-r" style={{ background: `color-mix(in srgb, ${r.color} 6%, transparent)` }}>
                <RepoChip k={r.key} />
                <div className="mt-3 font-mono text-[11px] text-mute">github.com/{r.slug}</div>
                <p className="mt-3 text-[13.5px] leading-relaxed text-[#b9c1d0]">{r.tagline}</p>
                <dl className="mt-4 space-y-2 text-[12px]">
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-widest text-mute">Language</dt>
                    <dd className="text-[#d5d9e2]">{r.lang}</dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-widest text-mute">License</dt>
                    <dd className="text-[#d5d9e2]">{r.license}</dd>
                  </div>
                  <div>
                    <dt className="font-mono text-[10px] uppercase tracking-widest text-mute">Scale</dt>
                    <dd className="text-[#d5d9e2]">{r.size}</dd>
                  </div>
                </dl>
              </div>
              <div className="p-5">
                <div className="mb-1 font-mono text-[10px] uppercase tracking-widest" style={{ color: r.color }}>
                  Signature idea
                </div>
                <p className="mb-4 text-[15px] font-medium leading-snug text-white">{r.signature}</p>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-[#34d399]">Taken into the fusion</div>
                    <ul className="space-y-1">
                      {r.took.map((t) => (
                        <li key={t} className="flex gap-2 text-[13px] text-[#c9cfdb]">
                          <span className="text-[#34d399]">+</span>
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-mute">Left on purpose</div>
                    <ul className="space-y-1">
                      {r.left.map((t) => (
                        <li key={t} className="flex gap-2 text-[13px] text-mute">
                          <span>–</span>
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="mt-4 border-t border-line pt-3 text-[12px] text-mute">
                  <span className="font-mono uppercase tracking-widest">Verified </span>
                  {r.verified}
                </div>
              </div>
            </div>
          </Panel>
        ))}
      </div>

      <Panel className="p-5">
        <h4 className="mb-2 text-[15px] font-semibold text-white">Two things worth knowing before you adopt any of this</h4>
        <ul className="space-y-2 text-[14px] leading-relaxed text-[#b9c1d0]">
          <li>
            <b className="text-white">Headline sizes go stale.</b> nanobot advertises about 4,000 lines of core. At HEAD,{" "}
            <code className="font-mono text-[12px] text-nanobot">nanobot/agent/loop.py</code> alone is 2,671 lines. Waku's claim, by contrast, held when I measured it.
          </li>
          <li>
            <b className="text-white">Licenses differ in ways that matter.</b> Five are MIT and memU is Apache-2.0. Waku's name and mark are not MIT (LICENSE-BRAND), and its hosted/ directory is Elastic 2.0:
            run it yourself, but you cannot resell it as a service. The fusion code is original and carries neither restriction.
          </li>
        </ul>
      </Panel>
    </div>
  );
}
