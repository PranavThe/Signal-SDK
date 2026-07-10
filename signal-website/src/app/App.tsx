import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { motion, useInView, useScroll, useTransform } from "motion/react";
import { TrendingUp, Zap, Clock, BookOpen, Copy, Check } from "lucide-react";


/* ─── Scroll-reveal wrapper ─── */
function Reveal({
  children,
  delay = 0,
  y = 28,
  className = "",
}: {
  children: React.ReactNode; delay?: number; y?: number; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, y }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

/* ─── Stats ticker ─── */
function StatsTicker() {
  const items = [
    { value: "2 lines", label: "To integrate" },
    { value: "Real-time", label: "Human escalations" },
    { value: "Auto-learns", label: "From every decision" },
    { value: "Progressive", label: "Autonomy growth" },
    { value: "Zero", label: "Repeated questions" },
    { value: "Built-in", label: "Dashboard & analytics" },
    { value: "async/await", label: "Python SDK" },
    { value: "Production", label: "Ready out of box" },
  ];
  const doubled = [...items, ...items];
  return (
    <div className="overflow-hidden border-y border-border py-4" style={{ background: "#0d0d0b" }}>
      <div
        className="flex gap-16 whitespace-nowrap"
        style={{ animation: "ticker 32s linear infinite", width: "max-content" }}
      >
        {doubled.map((item, i) => (
          <div key={i} className="flex items-baseline gap-3 shrink-0">
            <span className="text-lg font-bold tracking-tight" style={{ fontFamily: "'Manrope', sans-serif", color: "#f7f7f5" }}>
              {item.value}
            </span>
            <span className="text-xs tracking-widest uppercase" style={{ fontFamily: "'Geist Mono', monospace", color: "#4a4a47" }}>
              {item.label}
            </span>
            <span className="text-2xl" style={{ color: "#2a2a28", marginLeft: "1rem" }}>·</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Loop step ─── */
function LoopStep({ n, title, body, active, delay }: {
  n: string; title: string; body: string; active?: boolean; delay: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 24 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay }}
      className="relative flex flex-col gap-4 transition-all duration-500 cursor-default"
      style={{
        background: active ? "#0d0d0b" : "#ffffff",
        border: "1px solid",
        borderColor: active ? "#0d0d0b" : "rgba(13,13,11,0.09)",
        padding: "2rem",
      }}
    >
      <div
        className="w-8 h-8 flex items-center justify-center text-xs font-bold"
        style={{
          fontFamily: "'Geist Mono', monospace",
          background: active ? "#f7f7f5" : "#0d0d0b",
          color: active ? "#0d0d0b" : "#f7f7f5",
          transition: "background 0.5s, color 0.5s",
        }}
      >
        {n}
      </div>
      <h3
        className="text-base font-semibold leading-snug transition-colors duration-500"
        style={{ fontFamily: "'Manrope', sans-serif", color: active ? "#f7f7f5" : "#0d0d0b" }}
      >
        {title}
      </h3>
      <p
        className="text-sm leading-relaxed font-light transition-colors duration-500"
        style={{ fontFamily: "'Manrope', sans-serif", color: active ? "#9a9a97" : "#6a6a67" }}
      >
        {body}
      </p>
    </motion.div>
  );
}

/* ─── Copyable install command ─── */
function InstallCommand() {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText("pip install signalops");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.3 }}
      className="group relative flex max-w-full items-center gap-3 px-4 py-3 border border-border hover:border-foreground/20 transition-all cursor-pointer"
      onClick={handleCopy}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      style={{
        background: "linear-gradient(135deg, #f7f7f5 0%, #efefed 100%)",
      }}
    >
      <motion.div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500"
        style={{
          background: "linear-gradient(90deg, transparent, rgba(13,13,11,0.03), transparent)",
          backgroundSize: "200% 100%",
        }}
        animate={{
          backgroundPosition: ["200% 0", "-200% 0"],
        }}
        transition={{
          duration: 2,
          repeat: Infinity,
          ease: "linear",
        }}
      />
      <code
        className="text-sm font-medium tracking-tight relative z-10"
        style={{ fontFamily: "'Geist Mono', monospace", color: "#0d0d0b" }}
      >
        pip install signalops
      </code>
      <motion.div
        className="relative z-10"
        animate={copied ? { scale: [1, 1.2, 1] } : {}}
        transition={{ duration: 0.3 }}
      >
        {copied ? (
          <Check size={16} strokeWidth={2.5} style={{ color: "#0d0d0b" }} />
        ) : (
          <Copy size={16} strokeWidth={2} style={{ color: "#6a6a67" }} className="group-hover:opacity-100 opacity-60 transition-opacity" />
        )}
      </motion.div>
    </motion.div>
  );
}

/* ══════════════════════════════════════════ */
export default function App() {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [activeLoop, setActiveLoop] = useState(0);
  const dashboardHref = "/dashboard";
  const dashboardDisplayUrl =
    typeof window !== "undefined" ? `${window.location.origin}/dashboard` : "/dashboard";

  /* Form ref for scrolling */
  const formRef = useRef<HTMLDivElement>(null);

  /* Loop auto-advance */
  useEffect(() => {
    const t = setInterval(() => setActiveLoop((n) => (n + 1) % 4), 2400);
    return () => clearInterval(t);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (subject && message) {
      const mailtoLink = `mailto:pranavpuranik07@gmail.com?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message)}`;
      window.location.href = mailtoLink;
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground relative" style={{ fontFamily: "'Manrope', sans-serif" }}>
      <style>{`
        @keyframes ticker { from{transform:translateX(0)} to{transform:translateX(-50%)} }
        @keyframes scoreGlow {
          0%,100%{opacity:1;transform:scale(1)}
          50%{opacity:0.75;transform:scale(1.01)}
        }
        @keyframes floatSlow {
          0%,100%{transform:translateY(0px)}
          50%{transform:translateY(-8px)}
        }
        @keyframes pulse {
          0%,100%{transform:scale(1);opacity:1}
          50%{transform:scale(1.02);opacity:0.95}
        }
        @keyframes shimmer {
          0%{background-position:200% center}
          100%{background-position:-200% center}
        }
        ::-webkit-scrollbar { display:none }
        * { scrollbar-width: none }
        html, body, #root { max-width: 100%; overflow-x: hidden; }
      `}</style>


      {/* ── Nav ── */}
      <motion.nav
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between gap-4 px-4 py-4 sm:px-8 bg-background/80 backdrop-blur-md"
        style={{ borderBottom: "1px solid rgba(13,13,11,0.07)" }}
      >
        {/* Logo */}
        <div className="relative flex items-center gap-3">
          <img src="/signal-logo-black.png" alt="Signal" className="h-7 w-auto sm:h-9" style={{ filter: "invert(1) brightness(1.5)" }} />
        </div>
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          <Link to="/docs">
            <motion.div
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.97 }}
              className="text-sm font-medium text-foreground hover:opacity-70 transition-opacity"
              style={{ fontFamily: "'Manrope', sans-serif" }}
            >
              Docs
            </motion.div>
          </Link>
          <motion.a
            href={dashboardHref}
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            className="text-sm font-medium text-foreground hover:opacity-70 transition-opacity"
            style={{ fontFamily: "'Manrope', sans-serif" }}
          >
            Dashboard
          </motion.a>
        </div>
      </motion.nav>

      {/* ── Hero ── */}
      <section className="relative pt-28 pb-0 px-4 sm:px-8 md:px-14 max-w-screen-xl mx-auto overflow-visible sm:pt-36">
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1], delay: 0.1 }}
        >
          <p
            className="text-xs tracking-widest uppercase text-muted-foreground mb-8 font-medium"
            style={{ fontFamily: "'Geist Mono', monospace" }}
          >
            Operational Intelligence for AI Teams
          </p>

          <h1
            className="font-extrabold leading-[0.93] tracking-tighter"
            style={{ fontSize: "clamp(3.2rem, 9vw, 8.5rem)", fontFamily: "'Manrope', sans-serif", color: "#0d0d0b" }}
          >
            Human judgment
            <br />
            <motion.span
              animate={{
                opacity: [0.38, 0.55, 0.38],
                y: [0, -4, 0]
              }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
              style={{ color: "#acacaa", display: "inline-block" }}
            >
              should compound.
            </motion.span>
            <br />
            Not evaporate.
          </h1>

          <div className="mt-10 flex flex-col items-start gap-7 sm:mt-12 sm:gap-8">
            <p className="text-base md:text-lg font-light leading-relaxed max-w-2xl" style={{ color: "#6a6a67" }}>
              Signal turns every decision your team makes into permanent operational intelligence that every agent you run learns from automatically.
            </p>
            <InstallCommand />
          </div>
        </motion.div>

        {/* Dashboard */}
        <div className="mt-12 mb-0 relative sm:mt-16">
          <motion.div
            className="w-full rounded-t-xl overflow-hidden"
            animate={{ boxShadow: [
              "0 -4px 80px rgba(0,0,0,0.07), 0 0 0 1px rgba(13,13,11,0.04)",
              "0 -4px 100px rgba(0,0,0,0.09), 0 0 0 1px rgba(13,13,11,0.06)",
              "0 -4px 80px rgba(0,0,0,0.07), 0 0 0 1px rgba(13,13,11,0.04)"
            ]}}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
            style={{
              background: "#ffffff",
              border: "1px solid rgba(13,13,11,0.09)",
            }}
          >
            {/* Browser chrome */}
            <div
              className="flex items-center gap-2 px-3 py-3 sm:px-5 sm:py-3.5"
              style={{ borderBottom: "1px solid rgba(13,13,11,0.07)", background: "#f7f7f5" }}
            >
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#d0d0ce" }} />
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#d0d0ce" }} />
              <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#d0d0ce" }} />
              <div
                className="ml-2 min-w-0 flex-1 truncate px-3 py-1 text-[10px] rounded-sm sm:ml-4 sm:text-xs"
                style={{ fontFamily: "'Geist Mono', monospace", color: "#6a6a67", background: "#efefed" }}
              >
                {dashboardDisplayUrl}
              </div>
            </div>

            {/* Dashboard Image */}
            <div className="h-[280px] overflow-hidden sm:h-[420px] lg:h-[500px]">
              <img
                src="/sample-dashboard.png"
                alt="Signal Dashboard"
                style={{
                  width: "calc(100% + 10px)",
                  height: "100%",
                  objectFit: "cover",
                  objectPosition: "top left",
                  display: "block",
                  marginLeft: "-5px"
                }}
              />
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── Stats ticker ── */}
      <StatsTicker />

      {/* ── Problem ── */}
      <section className="py-16 px-4 sm:px-8 md:px-14 sm:py-24 max-w-screen-xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border">
          {[
            { n: "01", text: "Your agents ask the same question twice. Nothing they learn sticks." },
            { n: "02", text: "Every human decision evaporates into a Slack thread nobody will find." },
            { n: "03", text: "Your company gets smarter individually. Your system stays dumb." },
          ].map((item, i) => (
            <Reveal key={item.n} delay={i * 0.12} className="bg-background">
              <div className="p-6 group h-full sm:p-10">
                <span className="block text-xs mb-8 text-muted-foreground" style={{ fontFamily: "'Geist Mono', monospace" }}>
                  {item.n}
                </span>
                <p className="text-xl font-light leading-relaxed text-foreground/80 group-hover:text-foreground transition-colors" style={{ fontFamily: "'Manrope', sans-serif" }}>
                  {item.text}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── The Loop ── */}
      <section className="py-16 px-4 sm:px-8 md:px-14 sm:py-24 max-w-screen-xl mx-auto border-t border-border relative overflow-hidden">
        <Reveal className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-16">
          <p className="text-xs tracking-widest uppercase text-muted-foreground font-medium" style={{ fontFamily: "'Geist Mono', monospace" }}>
            The Loop
          </p>
          <p className="text-sm text-muted-foreground max-w-xs text-right font-light hidden md:block" style={{ fontFamily: "'Manrope', sans-serif" }}>
            This is the product in one visual.
          </p>
        </Reveal>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-px bg-border">
          {[
            { n: "01", title: "Agent encounters uncertainty", body: "A question arises that isn't covered by existing operational rules. The agent pauses rather than guessing." },
            { n: "02", title: "Human decides in one click", body: "The right person is surfaced instantly. They see the context, they decide. One click. Ten seconds." },
            { n: "03", title: "Signal extracts a rule", body: "That decision is parsed into a structured, permanent policy. No documentation required." },
            { n: "04", title: "Every future agent runs on it", body: "No human ever answers that question again. The system is now smarter, permanently." },
          ].map((step, i) => (
            <LoopStep key={i} n={step.n} title={step.title} body={step.body} active={activeLoop === i} delay={i * 0.1} />
          ))}
        </div>
      </section>

      {/* ── Stack (dark) ── */}
      <section className="py-16 px-4 sm:px-8 md:px-14 sm:py-24 relative overflow-hidden" style={{ background: "#0d0d0b" }}>
        <div className="max-w-screen-xl mx-auto grid md:grid-cols-2 gap-20 items-center relative z-10">
          <Reveal y={20}>
            <p className="text-xs tracking-widest uppercase mb-8 font-medium" style={{ fontFamily: "'Geist Mono', monospace", color: "#6a6a67" }}>
              Where Signal Sits
            </p>
            <p className="text-2xl md:text-3xl font-light leading-[1.4]" style={{ fontFamily: "'Manrope', sans-serif", color: "#f7f7f5" }}>
              Every agent stack has three layers. Models provide reasoning. Frameworks provide execution.{" "}
              <span style={{ color: "#9a9a97" }}>
                Signal provides operational intelligence — the accumulated judgment of how your company actually makes decisions.
              </span>
            </p>
          </Reveal>

          <Reveal y={20} delay={0.15}>
            <div className="space-y-px">
              {[
                { label: "Models",     sub: "Reasoning layer",          tag: "GPT-4o · Claude · Gemini",      highlight: false },
                { label: "Frameworks", sub: "Execution layer",          tag: "LangChain · CrewAI · AutoGen",   highlight: false },
                { label: "Signal",     sub: "Operational Intelligence", tag: "Your company's accumulated judgment", highlight: true },
              ].map((layer, i) => (
                <motion.div
                  key={i}
                  whileHover={{ x: layer.highlight ? 0 : 4 }}
                  transition={{ type: "spring", stiffness: 400, damping: 28 }}
                  className="flex flex-col items-start justify-between gap-4 p-5 sm:flex-row sm:items-center sm:p-6"
                  style={{
                    background: layer.highlight ? "#f7f7f5" : "#1a1a18",
                    color: layer.highlight ? "#0d0d0b" : "#9a9a97",
                    ...(layer.highlight ? { animation: "breatheRingDk 3.5s ease-in-out infinite" } : {}),
                  }}
                >
                  <div>
                    <div className="text-sm font-bold mb-1" style={{ fontFamily: "'Manrope', sans-serif", color: layer.highlight ? "#0d0d0b" : "#f7f7f5" }}>
                      {layer.label}
                    </div>
                    <div className="text-xs" style={{ fontFamily: "'Geist Mono', monospace", color: layer.highlight ? "#6a6a67" : "#4a4a47" }}>
                      {layer.tag}
                    </div>
                  </div>
                  <div className="text-xs shrink-0" style={{ fontFamily: "'Geist Mono', monospace", color: layer.highlight ? "#acacaa" : "#3a3a37" }}>
                    {layer.sub}
                  </div>
                </motion.div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── Integration ── */}
      <section className="py-16 px-4 sm:px-8 md:px-14 sm:py-24 max-w-screen-xl mx-auto border-b border-border">
        <div className="grid md:grid-cols-2 gap-16 items-center">
          <Reveal delay={0.05}>
            <div
              className="rounded-lg overflow-hidden"
              style={{
                background: "#0d0d0b",
                border: "1px solid rgba(255,255,255,0.06)",
                boxShadow: "0 20px 60px rgba(0,0,0,0.12)",
              }}
            >
              <div className="flex items-center gap-2 px-5 py-3.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#2a2a28" }} />
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#2a2a28" }} />
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: "#2a2a28" }} />
                <span className="ml-3 text-xs" style={{ fontFamily: "'Geist Mono', monospace", color: "#4a4a47" }}>agent.py</span>
              </div>
              <pre className="p-4 text-xs leading-[1.9] overflow-x-auto sm:p-7 sm:text-sm" style={{ fontFamily: "'Geist Mono', monospace" }}>
                <code>
                  <span style={{ color: "#4a4a47" }}>{"# Auto-resolves via rules, or escalates to human\n"}</span>
                  <span style={{ color: "#9a9a97" }}>{"result "}</span>
                  <span style={{ color: "#6a6a67" }}>{"= "}</span>
                  <span style={{ color: "#9a9a97" }}>{"await "}</span>
                  <span style={{ color: "#f7f7f5" }}>{"signalops"}</span>
                  <span style={{ color: "#6a6a67" }}>{"."}</span>
                  <span style={{ color: "#efefed" }}>{"escalate"}</span>
                  <span style={{ color: "#6a6a67" }}>{"(\n    "}</span>
                  <span style={{ color: "#9a9a97" }}>{"agent_id"}</span>
                  <span style={{ color: "#6a6a67" }}>=</span>
                  <span style={{ color: "#7c9a6e" }}>{'"support-bot"'}</span>
                  <span style={{ color: "#6a6a67" }}>{",\n    "}</span>
                  <span style={{ color: "#9a9a97" }}>{"question"}</span>
                  <span style={{ color: "#6a6a67" }}>=</span>
                  <span style={{ color: "#7c9a6e" }}>{'"Should I approve this?"'}</span>
                  <span style={{ color: "#6a6a67" }}>{",\n    "}</span>
                  <span style={{ color: "#9a9a97" }}>{"context"}</span>
                  <span style={{ color: "#6a6a67" }}>=</span>
                  <span style={{ color: "#9a9a97" }}>{"data"}</span>
                  <span style={{ color: "#6a6a67" }}>{"\n)\n\n"}</span>
                  <span style={{ color: "#4a4a47" }}>{"# Returns immediately if rule exists\n"}</span>
                  <span style={{ color: "#4a4a47" }}>{"# Waits for human if no rule\n"}</span>
                </code>
              </pre>
            </div>
          </Reveal>

          <Reveal delay={0.18}>
            <p className="text-xs tracking-widest uppercase text-muted-foreground mb-8 font-medium" style={{ fontFamily: "'Geist Mono', monospace" }}>
              The Integration
            </p>
            <p className="text-3xl md:text-4xl font-extrabold leading-tight tracking-tight mb-6" style={{ fontFamily: "'Manrope', sans-serif" }}>
              One function call.
            </p>
            <p className="text-lg font-light leading-relaxed text-muted-foreground" style={{ fontFamily: "'Manrope', sans-serif" }}>
              {"That's the entire integration. Add escalate() to your agent. Everything else is automatic."}
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── Moat ── */}
      <section className="py-20 px-4 sm:px-8 md:px-14 sm:py-32 max-w-screen-xl mx-auto relative overflow-hidden">
        <Reveal y={24} className="max-w-3xl">
          <p className="text-2xl md:text-4xl font-light leading-[1.5] text-foreground/80" style={{ fontFamily: "'Manrope', sans-serif" }}>
            The company that has been running Signal for a year has operational intelligence that cannot be replicated by a competitor who starts today.{" "}
            <span className="text-foreground font-semibold">
              Not because the software is hard to copy. Because twelve months of accumulated human judgment cannot be copied at all.
            </span>
          </p>
        </Reveal>
      </section>

      {/* ── Real Competitor ── */}
      <section className="py-16 px-4 sm:px-8 md:px-14 sm:py-20 border-t border-border">
        <div className="max-w-screen-xl mx-auto grid md:grid-cols-[1fr_2fr] gap-16 items-start">
          <Reveal>
            <p className="text-xs tracking-widest uppercase text-muted-foreground font-medium" style={{ fontFamily: "'Geist Mono', monospace" }}>
              The Real Competitor
            </p>
          </Reveal>
          <Reveal delay={0.1} y={16}>
            <p className="text-xl md:text-2xl font-light leading-[1.6] text-foreground/80" style={{ fontFamily: "'Manrope', sans-serif" }}>
              Your real competitor is not another startup. It is Notion documents nobody reads, Slack threads nobody finds, and institutional knowledge that walks out the door when someone quits.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ── CTA Footer ── */}
      <footer className="relative overflow-hidden" style={{ background: "#0d0d0b" }}>
        <div className="relative z-10 max-w-screen-xl mx-auto px-4 py-20 sm:px-8 md:px-14 sm:py-28">
          <Reveal y={24}>
            <h2
              className="font-extrabold leading-[0.93] tracking-tighter mb-10"
              style={{
                fontFamily: "'Manrope', sans-serif",
                fontSize: "clamp(2.5rem, 6vw, 5rem)",
                color: "#f7f7f5",
              }}
            >
              Human judgment
              <br />
              <motion.span
                animate={{
                  opacity: [0.28, 0.45, 0.28],
                  y: [0, -4, 0]
                }}
                transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
                style={{ color: "#4a4a47", display: "inline-block" }}
              >
                should compound.
              </motion.span>
              <br />
              Not evaporate.
            </h2>

            <p className="text-sm mb-8 font-light" style={{ fontFamily: "'Manrope', sans-serif", color: "#6a6a67" }}>
              Questions? Reach out to us directly.
            </p>

            <form ref={formRef} onSubmit={handleSubmit} className="flex flex-col gap-3 max-w-xl">
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Subject"
                required
                className="w-full px-5 py-3.5 text-sm border rounded-none focus:outline-none transition-colors"
                style={{
                  fontFamily: "'Manrope', sans-serif",
                  color: "#f7f7f5",
                  background: "rgba(255,255,255,0.04)",
                  borderColor: "rgba(255,255,255,0.1)",
                }}
              />
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Your message..."
                required
                rows={6}
                className="w-full px-5 py-3.5 text-sm border rounded-none focus:outline-none transition-colors resize-none"
                style={{
                  fontFamily: "'Manrope', sans-serif",
                  color: "#f7f7f5",
                  background: "rgba(255,255,255,0.04)",
                  borderColor: "rgba(255,255,255,0.1)",
                }}
              />
              <motion.button
                type="submit"
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.97 }}
                className="px-8 py-4 font-bold text-xs self-start"
                style={{
                  background: "#f7f7f5",
                  color: "#0d0d0b",
                  fontFamily: "'Manrope', sans-serif",
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                }}
              >
                Contact Us
              </motion.button>
            </form>
          </Reveal>

          <div
            className="mt-24 pt-8 flex items-center justify-between gap-6 flex-wrap"
            style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
          >
            <img src="/signal-logo-black.png" alt="Signal" className="h-5 w-auto opacity-80" />
            <p className="text-xs" style={{ fontFamily: "'Geist Mono', monospace", color: "#4a4a47" }}>
              © 2025 Signal · Operational Intelligence for AI Teams
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
