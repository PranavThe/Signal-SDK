import React, { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { Github, Check, X } from "lucide-react";
import { motion, useInView } from "motion/react";

function Reveal({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 24 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

export default function Docs() {
  const [activeSection, setActiveSection] = useState("overview");

  useEffect(() => {
    const handleScroll = () => {
      const sections = [
        "overview",
        "getting-started",
        "dashboard-guide",
        "sdk-reference",
        "use-cases",
        "best-practices",
        "security",
        "troubleshooting"
      ];

      for (let i = 0; i < sections.length; i++) {
        const section = sections[i];
        const element = document.getElementById(section);
        if (element) {
          const rect = element.getBoundingClientRect();
          if (rect.top >= 0 && rect.top <= 200) {
            setActiveSection(section);
            break;
          }
        }
      }
    };

    window.addEventListener("scroll", handleScroll);
    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  const navItems = [
    { id: "overview", label: "Overview" },
    { id: "getting-started", label: "Getting Started" },
    { id: "dashboard-guide", label: "Dashboard Guide" },
    { id: "sdk-reference", label: "SDK Reference" },
    { id: "use-cases", label: "Use Cases" },
    { id: "best-practices", label: "Best Practices" },
    { id: "security", label: "Security" },
    { id: "troubleshooting", label: "Troubleshooting" }
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#f7f7f5", fontFamily: "'Manrope', sans-serif" }}>
      {/* Navigation */}
      <nav style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "1rem 2rem",
        background: "rgba(247,247,245,0.8)",
        backdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(13,13,11,0.07)"
      }}>
        <Link to="/" style={{ display: "flex", alignItems: "center" }}>
          <img src="/signal-logo-black.png" alt="Signal" style={{ height: "2.25rem", width: "auto", filter: "invert(1) brightness(1.5)" }} />
        </Link>
        <div style={{ display: "flex", gap: "1.5rem", alignItems: "center" }}>
          <Link to="/" style={{ fontSize: "0.875rem", fontWeight: 500, color: "#0d0d0b", textDecoration: "none" }}>Home</Link>
          <a href="https://signal-omega-tan.vercel.app/dashboard" target="_blank" rel="noopener noreferrer" style={{ fontSize: "0.875rem", fontWeight: 500, color: "#0d0d0b", textDecoration: "none" }}>Dashboard</a>
          <a href="https://github.com/PranavThe/Signal-SDK" target="_blank" rel="noopener noreferrer" style={{ display: "flex", alignItems: "center", justifyContent: "center", width: "2.25rem", height: "2.25rem", color: "#0d0d0b" }}>
            <Github size={20} strokeWidth={1.5} />
          </a>
        </div>
      </nav>

      <div style={{ paddingTop: "8rem", paddingBottom: "4rem" }}>
        <div style={{ maxWidth: "1400px", margin: "0 auto", padding: "0 2rem", display: "grid", gridTemplateColumns: "240px 1fr", gap: "4rem" }}>

          {/* Sidebar */}
          <aside style={{ position: "sticky", top: "7rem", alignSelf: "start" }}>
            <p style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "#6a6a67", marginBottom: "1rem", fontFamily: "'Geist Mono', monospace", fontWeight: 600 }}>
              Contents
            </p>
            <nav style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {navItems.map((item) => {
                const isActive = activeSection === item.id;
                return (
                  <a
                    key={item.id}
                    href={"#" + item.id}
                    style={{
                      fontSize: "0.875rem",
                      color: isActive ? "#0d0d0b" : "#6a6a67",
                      textDecoration: "none",
                      paddingLeft: "0.75rem",
                      paddingTop: "0.25rem",
                      paddingBottom: "0.25rem",
                      borderLeft: isActive ? "2px solid #0d0d0b" : "2px solid transparent",
                      fontWeight: isActive ? 600 : 400,
                      transition: "all 0.2s ease"
                    }}
                  >
                    {item.label}
                  </a>
                );
              })}
            </nav>
          </aside>

          {/* Main Content */}
          <article style={{ maxWidth: "56rem" }}>
            {/* Header */}
            <Reveal>
              <div style={{ marginBottom: "4rem" }}>
                <p style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "#6a6a67", marginBottom: "1.5rem", fontFamily: "'Geist Mono', monospace" }}>
                  Documentation
                </p>
                <h1 style={{ fontSize: "3.5rem", fontWeight: 800, lineHeight: 1.1, marginBottom: "1.5rem", color: "#0d0d0b" }}>
                  Signal Documentation
                </h1>
                <p style={{ fontSize: "1.125rem", fontWeight: 300, lineHeight: 1.6, color: "#6a6a67" }}>
                  Everything you need to build autonomous AI agents with human-in-the-loop decision making.
                </p>
              </div>
            </Reveal>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "4rem" }} />

            {/* Overview */}
            <section id="overview" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "1.5rem", color: "#0d0d0b" }}>Overview</h2>
                <p style={{ fontSize: "1.0625rem", lineHeight: 1.7, marginBottom: "2rem", color: "#4a4a47" }}>
                  Signal is a human-in-the-loop decision framework for AI agents. It allows you to build autonomous agents that escalate critical decisions to humans, learn from those decisions, and progressively become more autonomous over time.
                </p>

                <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", marginTop: "2.5rem", color: "#0d0d0b" }}>Key Features</h3>
                <div style={{ display: "grid", gap: "1rem" }}>
                  {[
                    { title: "Smart Escalations", desc: "Agents automatically escalate uncertain decisions to humans" },
                    { title: "Rule Learning", desc: "Convert human decisions into reusable rules for similar situations" },
                    { title: "Progressive Autonomy", desc: "Track how autonomous your agents become over time" },
                    { title: "Dashboard Management", desc: "Web interface for reviewing decisions and managing rules" },
                    { title: "Real-time Monitoring", desc: "See agent decisions as they happen" }
                  ].map((feature, i) => (
                    <div key={i} style={{ padding: "1.25rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.5rem" }}>
                      <strong style={{ color: "#0d0d0b", fontSize: "0.9375rem" }}>{feature.title}</strong>
                      <span style={{ color: "#6a6a67", marginLeft: "0.5rem" }}>— {feature.desc}</span>
                    </div>
                  ))}
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Getting Started */}
            <section id="getting-started" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Getting Started</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>1. Create Your Account</h3>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Visit the Signal dashboard at your deployment URL</li>
                    <li>Sign up with your email address</li>
                    <li>You'll receive a confirmation email</li>
                  </ol>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>2. Set Up Your Organization</h3>
                  <p style={{ marginBottom: "0.75rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Navigate to Settings to configure your workspace:</p>
                  <ol style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li><strong>Create Organization:</strong> Enter your organization name and create your workspace</li>
                    <li><strong>Start Subscription:</strong> Set up billing (if required for your deployment)</li>
                    <li><strong>Generate API Key:</strong> Click "Generate new API key" to create your first key
                      <ul style={{ marginTop: "0.5rem" }}>
                        <li>Copy and save this key securely - it's only shown once</li>
                        <li>The key starts with <code style={{ background: "#0d0d0b", color: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", fontFamily: "'Geist Mono', monospace", fontSize: "0.875rem" }}>sk_live_</code></li>
                      </ul>
                    </li>
                  </ol>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>3. Install the SDK</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>bash</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.9375rem", fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>pip install signalops</pre>
                  </div>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>4. Integrate Signal into Your Agent</h3>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)", marginBottom: "1rem" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`import signalops

# Configure once
signalops.configure(api_key="sk_live_your_api_key_here")

# Escalate a decision
result = await signalops.escalate(
    agent_id="customer-support-bot",
    question="Should I issue a refund?",
    context=(
        "Customer ID: cust_123\\n"
        "Order Amount: $150\\n"
        "Reason: Product arrived damaged\\n"
        "Customer Tier: premium\\n"
        "Days Since Purchase: 3"
    ),
    metadata={
        "customer_id": "cust_123",
        "order_amount": 150
    }
)

# Use the decision
if result.decision in ["approve", "yes"]:
    issue_refund()
else:
    deny_refund()`}</pre>
                  </div>
                  <p style={{ fontSize: "0.9375rem", color: "#6a6a67", fontStyle: "italic" }}>
                    Note: Signal uses async/await, so your function must be async.
                  </p>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Dashboard Guide */}
            <section id="dashboard-guide" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Dashboard Guide</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Overview Tab</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>The Overview tab shows your agent's autonomy metrics:</p>
                  <div style={{ display: "grid", gap: "0.75rem" }}>
                    {[
                      "Total Agent Decisions Today — All decisions made by your agents",
                      "Handled Automatically — Decisions resolved using existing rules",
                      "Escalations Today — Decisions that required human review",
                      "Autonomy Score — Percentage of decisions handled automatically"
                    ].map((item, i) => (
                      <div key={i} style={{ paddingLeft: "1rem", borderLeft: "2px solid rgba(13,13,11,0.1)", color: "#4a4a47", fontSize: "0.9375rem" }}>
                        {item}
                      </div>
                    ))}
                  </div>
                  <p style={{ marginTop: "1.5rem", color: "#4a4a47", fontSize: "1.0625rem" }}>
                    Also includes: Autonomy Trend Table, AI-generated Suggestions for consolidating rules, Active Rules with trigger counts, and Recent Escalations.
                  </p>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1.5rem", color: "#0d0d0b" }}>Review Tab</h3>
                  <p style={{ marginBottom: "1.5rem", color: "#4a4a47", fontSize: "1.0625rem" }}>
                    The Review tab is where you make decisions on escalated requests. The workflow has three stages:
                  </p>
                  <div style={{ display: "grid", gap: "1rem" }}>
                    {[
                      { stage: "Stage 1: Decision", desc: "View context and similar past decisions, then click Approve or Reject" },
                      { stage: "Stage 2: Scope", desc: "Choose to create a rule for similar situations, or apply one-time only" },
                      { stage: "Stage 3: Review Rule", desc: "Review the AI-generated rule (WHEN/DO format) and approve, edit, or discard" }
                    ].map((s, i) => (
                      <div key={i} style={{ padding: "1.5rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.5rem" }}>
                        <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.5rem", color: "#0d0d0b" }}>{s.stage}</h4>
                        <p style={{ fontSize: "0.9375rem", color: "#6a6a67", margin: 0 }}>{s.desc}</p>
                      </div>
                    ))}
                  </div>
                  <p style={{ marginTop: "1.5rem", color: "#4a4a47", fontSize: "0.9375rem" }}>
                    Features auto-refresh every 5 seconds, button-specific loading states, and conflict warnings when rules overlap.
                  </p>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Rules Tab</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>
                    Displays all approved rules in a visual card format with:
                  </p>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "0.9375rem" }}>
                    <li>Status badges (Active, Paused, Pending)</li>
                    <li>Confidence levels (High, Medium, Low)</li>
                    <li>Trigger counts and timestamps</li>
                    <li>Real-time search and filtering</li>
                    <li>Bulk actions for managing multiple rules</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Escalations Tab</h3>
                  <p style={{ color: "#4a4a47", fontSize: "1.0625rem" }}>
                    Complete history of all agent escalations with searchable table showing time, agent, context, status, decision, and whether a rule was created. Click any row to expand full details.
                  </p>
                </div>

                <div style={{ marginTop: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Settings Tab</h3>
                  <p style={{ color: "#4a4a47", fontSize: "1.0625rem" }}>
                    Configure your organization, manage API keys, switch between organizations, and control team access.
                  </p>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* SDK Reference */}
            <section id="sdk-reference" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>SDK Reference</h2>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>configure()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Configure Signal globally:</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`signalops.configure(
    api_key="sk_live_your_api_key_here",
    base_url="https://your-signal-deployment.com"  # Optional
)`}</pre>
                  </div>
                </div>

                <div style={{ marginBottom: "3rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>escalate()</h3>
                  <p style={{ marginBottom: "1.5rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Escalate a decision to Signal and wait for human review:</p>

                  <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Parameters</h4>
                  <div style={{ display: "grid", gap: "0.75rem", marginBottom: "2rem" }}>
                    {[
                      { name: "agent_id", type: "str", desc: "Unique identifier for your agent" },
                      { name: "question", type: "str", desc: "Clear description of what decision is needed" },
                      { name: "context", type: "str", desc: "Text description formatted as field:value pairs" },
                      { name: "metadata", type: "dict, optional", desc: "Additional structured data" },
                      { name: "action", type: "str, optional", desc: "Action identifier for this decision type" },
                      { name: "timeout_seconds", type: "int, optional", desc: "How long to wait for a decision (default: 3600)" }
                    ].map((param, i) => (
                      <div key={i} style={{ padding: "1rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.375rem" }}>
                        <code style={{ fontSize: "0.875rem", fontWeight: 600, fontFamily: "'Geist Mono', monospace", color: "#0d0d0b" }}>{param.name}</code>
                        <span style={{ fontSize: "0.875rem", marginLeft: "0.5rem", color: "#6a6a67" }}>({param.type}) — {param.desc}</span>
                      </div>
                    ))}
                  </div>

                  <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Returns</h4>
                  <p style={{ marginBottom: "0.75rem", color: "#4a4a47", fontSize: "1.0625rem" }}>An EscalationResult object with:</p>
                  <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    {[
                      { field: "decision", desc: "The decision made (e.g., 'approve', 'reject')" },
                      { field: "rule_id", desc: "ID of the rule that made this decision (if auto-resolved)" },
                      { field: "auto_resolved", desc: "Whether resolved by a rule without human review" }
                    ].map((r, i) => (
                      <li key={i} style={{ paddingLeft: "1rem", borderLeft: "2px solid rgba(13,13,11,0.1)", color: "#4a4a47", fontSize: "0.9375rem" }}>
                        <code style={{ fontSize: "0.875rem", padding: "0.125rem 0.375rem", borderRadius: "0.25rem", background: "#0d0d0b", color: "#f7f7f5", fontFamily: "'Geist Mono', monospace" }}>{r.field}</code>
                        <span style={{ marginLeft: "0.5rem" }}>— {r.desc}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>check()</h3>
                  <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Check if an action should be allowed based on existing rules (without escalating):</p>
                  <div style={{ borderRadius: "0.5rem", overflow: "hidden", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                    <div style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", fontFamily: "'Geist Mono', monospace", color: "#4a4a47", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>python</div>
                    <pre style={{ padding: "1.25rem", fontSize: "0.875rem", lineHeight: 1.6, fontFamily: "'Geist Mono', monospace", color: "#f7f7f5", margin: 0, overflowX: "auto" }}>{`result = await signalops.check(
    action="action_name",
    context={"key": "value"},
    agent_id="your-agent-identifier"
)`}</pre>
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Use Cases */}
            <section id="use-cases" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Use Cases</h2>

                <div style={{ display: "grid", gap: "2rem" }}>
                  {[
                    { title: "Customer Support Automation", desc: "Automate refund approvals, account modifications, and support escalations based on customer tier, order value, and history." },
                    { title: "Content Moderation", desc: "Let AI handle clear cases while escalating edge cases to human moderators based on user reputation and content type." },
                    { title: "Financial Approvals", desc: "Review and approve transactions based on risk scores, account balance, and transaction patterns." },
                    { title: "HR Automation", desc: "Approve leave requests based on team coverage, remaining balance, and notice period." }
                  ].map((useCase, i) => (
                    <div key={i} style={{ padding: "2rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.5rem" }}>
                      <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "0.75rem", color: "#0d0d0b" }}>{useCase.title}</h3>
                      <p style={{ fontSize: "0.9375rem", color: "#6a6a67", margin: 0 }}>{useCase.desc}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Best Practices */}
            <section id="best-practices" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Best Practices</h2>

                <div style={{ display: "grid", gap: "2rem" }}>
                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>1. Clear Questions</h3>
                    <p style={{ marginBottom: "1rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Write questions that can be answered with approve/reject:</p>
                    <div style={{ display: "grid", gap: "0.75rem" }}>
                      <div style={{ padding: "1rem", borderRadius: "0.375rem", borderLeft: "4px solid #22c55e", background: "#f0fdf4" }}>
                        <p style={{ fontSize: "0.9375rem", margin: 0, color: "#166534" }}><strong>Good:</strong> "Should I issue a refund for this order?"</p>
                      </div>
                      <div style={{ padding: "1rem", borderRadius: "0.375rem", borderLeft: "4px solid #ef4444", background: "#fef2f2" }}>
                        <p style={{ fontSize: "0.9375rem", margin: 0, color: "#991b1b" }}><strong>Bad:</strong> "What should I do about this customer?"</p>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>2. Structured Context</h3>
                    <p style={{ color: "#4a4a47", fontSize: "1.0625rem" }}>Provide context as field:value pairs for dashboard readability.</p>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>3. Consistent Agent IDs</h3>
                    <p style={{ marginBottom: "0.75rem", color: "#4a4a47", fontSize: "1.0625rem" }}>Use descriptive identifiers:</p>
                    <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                      {["customer-support-refunds", "content-moderator-posts", "transaction-fraud-detector"].map((id, i) => (
                        <li key={i} style={{ paddingLeft: "1rem", borderLeft: "2px solid rgba(13,13,11,0.1)", color: "#4a4a47", fontSize: "0.9375rem" }}>
                          <code style={{ fontFamily: "'Geist Mono', monospace", background: "#0d0d0b", color: "#f7f7f5", padding: "0.125rem 0.375rem", borderRadius: "0.25rem" }}>{id}</code>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <div>
                    <h3 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>4. Monitor Autonomy Trends</h3>
                    <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                      {[
                        "Initial deployments: 20-40% autonomy is normal",
                        "Well-trained agents: 70-90% autonomy",
                        "Goal: Increase autonomy while maintaining quality"
                      ].map((item, i) => (
                        <li key={i} style={{ paddingLeft: "1rem", borderLeft: "2px solid rgba(13,13,11,0.1)", color: "#4a4a47", fontSize: "0.9375rem" }}>
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Security */}
            <section id="security" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Security</h2>

                <div style={{ marginBottom: "2.5rem" }}>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>API Key Management</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Store API keys in environment variables, never in code</li>
                    <li>Use different keys for development and production</li>
                    <li>Rotate keys periodically</li>
                    <li>Revoke keys immediately if compromised</li>
                  </ul>
                </div>

                <div>
                  <h3 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "1rem", color: "#0d0d0b" }}>Access Control</h3>
                  <ul style={{ paddingLeft: "1.5rem", lineHeight: 1.8, color: "#4a4a47", fontSize: "1.0625rem" }}>
                    <li>Only invite trusted team members to your organization</li>
                    <li>Use the Settings tab to manage organization access</li>
                    <li>Review escalation history for unusual patterns</li>
                  </ul>
                </div>
              </Reveal>
            </section>

            <div style={{ height: "1px", background: "rgba(13,13,11,0.1)", marginBottom: "5rem" }} />

            {/* Troubleshooting */}
            <section id="troubleshooting" style={{ marginBottom: "5rem", scrollMarginTop: "6rem" }}>
              <Reveal>
                <h2 style={{ fontSize: "2rem", fontWeight: 700, marginBottom: "2rem", color: "#0d0d0b" }}>Troubleshooting</h2>

                <div style={{ display: "grid", gap: "1rem" }}>
                  {[
                    { title: "\"No organization selected\" error", solution: "Go to Settings and create or select an organization, then generate an API key." },
                    { title: "Agent escalations not appearing", solution: "Check: API key is correct, organization is selected in dashboard, base URL matches your deployment." },
                    { title: "Rules not triggering", solution: "Check: Rule status is Active (not Paused), rule condition matches your context format exactly." },
                    { title: "Search not finding results", solution: "Try: Clear all filters first, check for typos in search query (search is case-insensitive but requires partial matches)." }
                  ].map((issue, i) => (
                    <div key={i} style={{ padding: "1.5rem", background: "#ffffff", border: "1px solid rgba(13,13,11,0.07)", borderRadius: "0.5rem" }}>
                      <h4 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem", color: "#0d0d0b" }}>{issue.title}</h4>
                      <p style={{ fontSize: "0.9375rem", color: "#6a6a67", margin: 0 }}><strong>Solution:</strong> {issue.solution}</p>
                    </div>
                  ))}
                </div>
              </Reveal>
            </section>

            {/* CTA */}
            <Reveal>
              <div style={{ marginTop: "5rem", padding: "3rem", borderRadius: "0.5rem", background: "#0d0d0b", border: "1px solid rgba(255,255,255,0.06)" }}>
                <h3 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "1rem", color: "#f7f7f5" }}>Ready to Get Started?</h3>
                <p style={{ fontSize: "1.0625rem", marginBottom: "2rem", color: "#9a9a97" }}>
                  Install the SDK and integrate Signal into your agent in minutes. Watch your autonomy score grow as your agent learns from every decision.
                </p>
                <a
                  href="https://signal-omega-tan.vercel.app/dashboard"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: "inline-block",
                    padding: "1rem 2rem",
                    fontWeight: 700,
                    fontSize: "0.9375rem",
                    background: "#f7f7f5",
                    color: "#0d0d0b",
                    textDecoration: "none",
                    letterSpacing: "0.03em",
                    borderRadius: "0.375rem",
                    transition: "transform 0.2s ease"
                  }}
                >
                  Go to Dashboard →
                </a>
              </div>
            </Reveal>
          </article>
        </div>
      </div>
    </div>
  );
}
