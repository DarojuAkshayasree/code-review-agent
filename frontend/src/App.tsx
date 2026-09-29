import { useEffect, useMemo, useState } from 'react';
import Editor from '@monaco-editor/react';

type Severity = 'critical' | 'high' | 'medium' | 'low' | 'suggestion';

type Finding = {
  id?: string;
  severity: Severity;
  category: string;
  title: string;
  description: string;
  suggestion: string;
  evidence?: string[] | string;
  team_rule_id?: string | null;
};

type ReviewResponse = {
  review_id: string;
  summary: string;
  score: number;
  findings: Finding[];
  memory_used: { rule: string; source: string }[];
};

type TeamRule = { id: string; text: string; category: string; source: string; created_at: string };
type ReviewRecord = ReviewResponse & { id: string; filename: string; language: string; created_at: string; findings: Finding[] };
type MemoryItem = { id: string; action: string; title: string; text: string; created_at: string };
type DashboardStats = {
  total_reviews: number;
  issues_found: number;
  team_rules: number;
  memory_items: number;
  memory_influenced_reviews: number;
  most_common_issue: string | null;
  recent_reviews: ReviewRecord[];
  ai_provider: string;
};

const languages = [
  { id: 'python', label: 'Python', extension: 'py' },
  { id: 'java', label: 'Java', extension: 'java' },
  { id: 'javascript', label: 'JavaScript', extension: 'js' },
  { id: 'typescript', label: 'TypeScript', extension: 'ts' },
  { id: 'c', label: 'C', extension: 'c' },
  { id: 'cpp', label: 'C++', extension: 'cpp' },
  { id: 'csharp', label: 'C#', extension: 'cs' },
  { id: 'go', label: 'Go', extension: 'go' },
];

const examples: Record<string, string> = {
  python: `@app.get("/users")\ndef get_users():\n    password = "demo-secret-12345"\n    print("loading users")\n    try:\n        return db.query("SELECT * FROM users")\n    except Exception:\n        return []\n`,
  java: `@RestController\npublic class UserController {\n    private final JdbcTemplate jdbcTemplate;\n    private String password = "demo-secret-12345";\n\n    @GetMapping("/users")\n    public List<User> getUsers() {\n        System.out.println("loading users");\n        try {\n            return jdbcTemplate.query("SELECT * FROM users", mapper);\n        } catch (Exception ex) {\n            return List.of();\n        }\n    }\n}`,
  javascript: `const apiKey = "demo-secret-12345";\napp.get("/users", async (req, res) => {\n  console.log("loading users");\n  const rows = await database.query("SELECT * FROM users");\n  res.send(rows);\n});\n`,
  typescript: `const password = "demo-secret-12345";\nrouter.get("/users", async (req, res) => {\n  console.log("loading users");\n  const rows = await database.query("SELECT * FROM users");\n  res.send(rows);\n});\n`,
  c: `#include <stdio.h>\n#include <string.h>\nint main(void) {\n    char name[16];\n    char *password = "demo-secret-12345";\n    gets(name);\n    printf("loaded %s\\n", name);\n    return 0;\n}\n`,
  cpp: `#include <cstdlib>\n#include <cstdio>\nint main() {\n    const char* api_key = "demo-secret-12345";\n    char* buffer = (char*)malloc(64);\n    strcpy(buffer, "debug");\n    std::cout << buffer;\n    return 0;\n}\n`,
  csharp: `public class UsersController : Controller {\n    private string password = "demo-secret-12345";\n    public IActionResult GetUsers() {\n        Console.WriteLine("loading users");\n        using var db = new SqlConnection(connectionString);\n        try { return Ok(db.Query("SELECT * FROM users")); }\n        catch (Exception) { return BadRequest(); }\n    }\n}\n`,
  go: `package main\n\nimport "fmt"\nimport "net/http"\n\nvar apiKey = "demo-secret-12345"\nvar db *sql.DB\n\nfunc users(w http.ResponseWriter, r *http.Request) {\n    fmt.Println("loading users")\n    rows, _ := db.Query("SELECT * FROM users")\n    _ = rows\n}\n`,
};

async function apiRequest<T>(baseUrl: string, path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data as T;
}

const baseCode = examples.python;

const defaultRule = 'Database calls must not happen directly inside Controllers. Use the Repository/Service layer.';

function App() {
  const [sidebar, setSidebar] = useState('Dashboard');
  const [filename, setFilename] = useState('users.py');
  const [language, setLanguage] = useState(() => localStorage.getItem('default-language') || 'python');
  const [code, setCode] = useState(baseCode);
  const [rules, setRules] = useState<TeamRule[]>([]);
  const [memoryItems, setMemoryItems] = useState<MemoryItem[]>([]);
  const [reviews, setReviews] = useState<ReviewRecord[]>([]);
  const [stats, setStats] = useState<DashboardStats>({ total_reviews: 0, issues_found: 0, team_rules: 0, memory_items: 0, memory_influenced_reviews: 0, most_common_issue: null, recent_reviews: [], ai_provider: 'Loading...' });
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [selectedHistory, setSelectedHistory] = useState<ReviewRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [apiError, setApiError] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [actionStatus, setActionStatus] = useState<Record<string, string>>({});
  const [teamRuleInput, setTeamRuleInput] = useState(defaultRule);
  const [apiUrl, setApiUrl] = useState(() => localStorage.getItem('review-api-url') || 'https://code-review-agent-3-82in.onrender.com');
  const [apiUrlDraft, setApiUrlDraft] = useState(apiUrl);
  const [defaultLanguage, setDefaultLanguage] = useState(() => localStorage.getItem('default-language') || 'python');
  const [demoMode, setDemoMode] = useState(() => localStorage.getItem('demo-mode') !== 'false');
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoResults, setDemoResults] = useState<{ first: ReviewResponse; second: ReviewResponse } | null>(null);

  const loadRules = async () => {
    const data = await apiRequest<{ rules: TeamRule[] }>(apiUrl, '/api/rules');
    setRules(data.rules ?? []);
  };

  const loadReviews = async () => {
    const data = await apiRequest<{ reviews: ReviewRecord[] }>(apiUrl, '/api/reviews');
    setReviews(data.reviews ?? []);
  };

  const refreshData = async () => {
    try {
      const [nextStats, memory, history] = await Promise.all([
        apiRequest<DashboardStats>(apiUrl, '/api/stats'),
        apiRequest<{ rules: TeamRule[]; items: MemoryItem[] }>(apiUrl, '/api/memory'),
        apiRequest<{ reviews: ReviewRecord[] }>(apiUrl, '/api/reviews'),
      ]);
      setStats(nextStats);
      setRules(memory.rules ?? []);
      setMemoryItems(memory.items ?? []);
      setReviews(history.reviews ?? []);
      setApiError('');
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Could not connect to the review backend.');
    }
  };

  useEffect(() => { void refreshData(); }, [apiUrl]);

  const addRule = async (text = teamRuleInput, source = 'manual') => {
    if (!text.trim()) return null;
    const data = await apiRequest<{ rule: TeamRule }>(apiUrl, '/api/rules', {
      method: 'POST',
      body: JSON.stringify({ text: text.trim(), category: 'architecture', source }),
    });
    setTeamRuleInput('');
    await refreshData();
    return data.rule;
  };

  const runReview = async (submittedCode = code, submittedLanguage = language, submittedFilename = filename): Promise<ReviewResponse | null> => {
    if (!submittedCode.trim()) {
      setError('Enter code before starting a review.');
      return null;
    }
    if (!languages.some((item) => item.id === submittedLanguage)) {
      setError('Choose a supported programming language.');
      return null;
    }
    setLoading(true);
    setError('');
    setReview(null);
    try {
      const data = await apiRequest<ReviewResponse>(apiUrl, '/api/review', {
        method: 'POST',
        body: JSON.stringify({ code: submittedCode, language: submittedLanguage, filename: submittedFilename }),
      });
      setReview(data);
      await refreshData();
      return data;
    } catch (err: any) {
      setError(err.message || 'Could not complete the review. Check that the backend is running.');
      return null;
    } finally {
      setLoading(false);
    }
  };

  const acceptFinding = async (findingId?: string) => {
    if (!review?.review_id || !findingId) return;
    try {
      await apiRequest(apiUrl, '/api/feedback', {
        method: 'POST',
        body: JSON.stringify({ review_id: review.review_id, finding_id: findingId, action: 'accepted' }),
      });
      setActionStatus((current) => ({ ...current, [`${review.review_id}:${findingId}`]: 'accepted' }));
      setActionMessage('Feedback saved to team memory.');
      await refreshData();
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Could not save accepted feedback.');
    }
  };

  const rejectFinding = async (findingId?: string) => {
    if (!review?.review_id || !findingId) return;
    try {
      await apiRequest(apiUrl, '/api/feedback', {
        method: 'POST',
        body: JSON.stringify({ review_id: review.review_id, finding_id: findingId, action: 'rejected' }),
      });
      setActionStatus((current) => ({ ...current, [`${review.review_id}:${findingId}`]: 'rejected' }));
      setActionMessage('Rejection recorded. It was not added as a team rule.');
      await refreshData();
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Could not save rejected feedback.');
    }
  };

  const addFindingRule = async (finding: Finding) => {
    const ruleText = finding.category === 'architecture' && finding.title.toLowerCase().includes('database')
      ? 'Database access must be handled through the Repository/Service layer instead of directly inside Controllers.'
      : finding.suggestion;
    try {
      const rule = await addRule(ruleText, `review:${review?.review_id ?? 'manual'}`);
      setActionMessage(rule ? 'Team rule added and visible in Team Memory.' : 'Enter a rule before saving.');
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : 'Could not add the team rule.');
    }
  };

  const deleteRule = async (ruleId: string) => {
    try {
      await apiRequest(apiUrl, `/api/rules/${ruleId}`, { method: 'DELETE' });
      await refreshData();
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Could not delete the rule.');
    }
  };

  const resetDemo = async () => {
    if (!window.confirm('Reset Demo permanently clears the local review history, feedback, and team rules. Continue?')) return;
    try {
      await apiRequest(apiUrl, '/api/demo/reset', { method: 'POST' });
      setReview(null);
      setDemoResults(null);
      setActionStatus({});
      setCode(baseCode);
      setLanguage('python');
      setFilename('users.py');
      setTeamRuleInput(defaultRule);
      setActionMessage('Demo data reset.');
      await refreshData();
    } catch (err) {
      setApiError(err instanceof Error ? err.message : 'Could not reset demo data.');
    }
  };

  const demoFlow = async () => {
    if (!window.confirm('Run Demo clears the local review history, feedback, and team rules to make the memory sequence easy to follow. Continue?')) return;
    setDemoRunning(true);
    setError('');
    setActionMessage('');
    setDemoResults(null);
    setSidebar('Code Review');
    try {
      await apiRequest(apiUrl, '/api/demo/reset', { method: 'POST' });
      await addRule(defaultRule, 'demo_setup');
      setLanguage('python');
      setFilename('users.py');
      const firstCode = examples.python;
      setCode(firstCode);
      const first = await runReview(firstCode, 'python', 'users.py');
      if (!first) return;
      const architectureFinding = first.findings.find((item) => item.category === 'architecture');
      if (!architectureFinding?.id) throw new Error('The first review did not return an architecture finding to accept.');
      await apiRequest(apiUrl, '/api/feedback', {
        method: 'POST',
        body: JSON.stringify({ review_id: first.review_id, finding_id: architectureFinding.id, action: 'accepted' }),
      });
      setActionStatus((current) => ({ ...current, [`${first.review_id}:${architectureFinding.id}`]: 'accepted' }));
      const secondCode = `@app.get("/accounts")\ndef get_accounts():\n    return db.query("SELECT id, email FROM accounts")\n`;
      setCode(secondCode);
      const second = await runReview(secondCode, 'python', 'users.py');
      if (second) {
        setDemoResults({ first, second });
        setActionMessage('The second review retrieved the accepted team decision from memory.');
      }
      await refreshData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The demo could not complete.');
    } finally {
      setDemoRunning(false);
    }
  };

  const scoreTone = useMemo(() => {
    if (!review) return 'border-slate-700';
    return review.score >= 80 ? 'border-emerald-500' : review.score >= 60 ? 'border-amber-500' : 'border-rose-500';
  }, [review]);

  const renderBadges = (severity: Severity) => {
    const map = {
      critical: 'bg-red-500/15 text-red-300 border-red-500/30',
      high: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
      medium: 'bg-yellow-500/15 text-yellow-200 border-yellow-500/30',
      low: 'bg-sky-500/15 text-sky-200 border-sky-500/30',
      suggestion: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30',
    };
    const label = {
      critical: 'Critical',
      high: 'High',
      medium: 'Medium',
      low: 'Low',
      suggestion: 'Suggestion',
    };
    return <span className={`inline-flex rounded-full border px-2 py-1 text-xs font-semibold ${map[severity]}`}>{label[severity]}</span>;
  };

  const content = (() => {
    if (sidebar === 'Dashboard') {
      return (
        <div className="space-y-6">
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: 'Total Reviews', value: stats.total_reviews },
              { label: 'Issues Found', value: stats.issues_found },
              { label: 'Team Rules', value: stats.team_rules },
              { label: 'Memory Items', value: stats.memory_items },
            ].map((stat) => <div key={stat.label} className="rounded-lg border border-slate-800 bg-slate-900/80 p-4"><div className="text-sm text-slate-400">{stat.label}</div><div className="mt-2 text-3xl font-semibold text-white">{stat.value}</div></div>)}
          </section>
          <section className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
            <div className="rounded-lg border border-slate-800 bg-slate-900/80 p-5">
              <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold text-white">Recent Reviews</h2><button onClick={() => setSidebar('Review History')} className="text-sm text-cyan-300">View history</button></div>
              {stats.recent_reviews.length ? stats.recent_reviews.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 py-3"><div><div className="font-medium text-slate-100">{item.filename || 'review file'}</div><div className="text-xs text-slate-400">{item.language} · {new Date(item.created_at).toLocaleString()}</div></div><div className="text-right text-sm"><div className="text-amber-300">Score {item.score}/100</div><div className="text-slate-400">{item.findings.filter((finding) => finding.severity !== 'suggestion').length} issues</div></div></div>) : <p className="text-sm text-slate-400">No reviews yet.</p>}
            </div>
            <div className="space-y-4">
              <div className="rounded-lg border border-cyan-900/70 bg-cyan-950/30 p-5"><h2 className="text-lg font-semibold text-white">How team memory shapes reviews</h2><p className="mt-2 text-sm leading-6 text-slate-300">Team rules and accepted recommendations are retrieved alongside similar past reviews. That context lets the reviewer reference decisions your team has already made instead of treating every submission in isolation.</p><div className="mt-4 space-y-2 text-sm"><div><strong className="text-cyan-200">{stats.memory_influenced_reviews}</strong> memory-influenced reviews</div><div>Most common issue: <strong className="text-slate-100">{stats.most_common_issue || 'None yet'}</strong></div></div></div>
              {apiError && <div className="rounded-lg border border-rose-500/40 bg-rose-950/30 p-4 text-sm text-rose-200">Backend unavailable: {apiError}</div>}
            </div>
          </section>
        </div>
      );
    }

    if (sidebar === 'Settings') {
      return (
        <section className="max-w-3xl rounded-lg border border-slate-800 bg-slate-900/80 p-5">
          <h2 className="text-lg font-semibold text-white">Settings</h2>
          <form className="mt-5 space-y-5" onSubmit={(event) => {
            event.preventDefault();
            const normalizedUrl = apiUrlDraft.trim().replace(/\/$/, '');
            localStorage.setItem('review-api-url', normalizedUrl);
            localStorage.setItem('default-language', defaultLanguage);
            localStorage.setItem('demo-mode', String(demoMode));
            setApiUrl(normalizedUrl);
            setActionMessage('Settings saved.');
          }}>
            <label className="block text-sm text-slate-300">Backend/API URL<input value={apiUrlDraft} onChange={(event) => setApiUrlDraft(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100" /></label>
            <label className="block text-sm text-slate-300">AI provider<div className="mt-2 rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100">{stats.ai_provider}</div></label>
            <label className="block text-sm text-slate-300">Default programming language<select value={defaultLanguage} onChange={(event) => setDefaultLanguage(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100">{languages.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
            <label className="flex items-center gap-3 text-sm text-slate-300"><input type="checkbox" checked={demoMode} onChange={(event) => setDemoMode(event.target.checked)} className="h-4 w-4 accent-cyan-500" />Demo mode controls enabled</label>
            <button type="submit" className="rounded-md bg-cyan-600 px-4 py-2 text-sm font-semibold text-white">Save settings</button>
            {actionMessage && <span className="ml-3 text-sm text-emerald-300">{actionMessage}</span>}
          </form>
        </section>
      );
    }

    if (sidebar === 'Team Memory') {
      return (
        <div className="space-y-6">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5">
            <h2 className="text-xl font-semibold text-white">Team Memory</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Persistent rules and accepted review guidance are retrieved during future reviews. Rejected feedback stays visible here for context but is never promoted to a team rule.</p>
            <div className="mt-4 flex gap-3">
              <input value={teamRuleInput} onChange={(e) => setTeamRuleInput(e.target.value)} className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="Add a team rule" />
              <button onClick={() => void addRule().catch((err) => setApiError(err instanceof Error ? err.message : 'Could not add the rule.'))} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white">Add Rule</button>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {rules.map((rule) => (
              <div key={rule.id} className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="rounded-full bg-blue-500/15 px-2 py-1 text-xs text-blue-300">{rule.category}</span>
                  <span className="text-xs text-slate-400">{rule.source} · {new Date(rule.created_at).toLocaleDateString()}</span>
                </div>
                <p className="text-sm text-slate-100">{rule.text}</p>
                <button onClick={() => void deleteRule(rule.id)} className="mt-3 text-xs text-rose-300 hover:text-rose-200">Delete Rule</button>
              </div>
            ))}
            {!rules.length && <p className="text-sm text-slate-400">No team rules have been added.</p>}
          </div>

          <div className="space-y-3">
            <h3 className="font-semibold text-white">Review Memory ({memoryItems.length})</h3>
            {memoryItems.map((item) => (
              <div key={item.id} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
                <div className="flex items-center justify-between gap-3"><span className={`text-xs font-semibold uppercase ${item.action === 'accepted' ? 'text-emerald-300' : 'text-slate-400'}`}>{item.action} feedback</span><span className="text-xs text-slate-400">{new Date(item.created_at).toLocaleDateString()}</span></div>
                <h4 className="mt-2 text-sm font-medium text-slate-100">{item.title}</h4><p className="mt-1 text-sm text-slate-400">{item.text}</p>
              </div>
            ))}
            {!memoryItems.length && <p className="text-sm text-slate-400">Accepted and rejected feedback will appear here.</p>}
          </div>
        </div>
      );
    }

    if (sidebar === 'Review History') {
      return (
        <div className="space-y-4">
          {reviews.map((item) => (
            <div key={item.id} className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-medium text-white">{item.filename || 'review.py'}</div>
                  <div className="text-xs text-slate-400">{item.language} · {new Date(item.created_at).toLocaleString()}</div>
                </div>
                <div className="text-right text-sm text-amber-300">Score: {item.score}/100<div className="text-xs text-slate-400">{item.findings.filter((finding) => finding.severity !== 'suggestion').length} issues</div></div>
              </div>
              <p className="mt-3 text-sm text-slate-300">{item.summary}</p>
              <button onClick={() => setSelectedHistory(item)} className="mt-3 text-sm text-cyan-300 hover:text-cyan-200">View review details</button>
            </div>
          ))}
          {!reviews.length && <p className="rounded-xl border border-slate-800 bg-slate-900/80 p-5 text-sm text-slate-400">No reviews in history.</p>}
          {selectedHistory && <div className="rounded-xl border border-cyan-900/70 bg-slate-900 p-5"><div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold text-white">{selectedHistory.filename} · {selectedHistory.language}</h3><p className="mt-1 text-sm text-slate-400">{selectedHistory.summary}</p></div><button onClick={() => setSelectedHistory(null)} className="text-sm text-slate-400 hover:text-white">Close</button></div><div className="mt-4 space-y-3">{selectedHistory.findings.map((finding) => <div key={finding.id || finding.title} className="border-t border-slate-800 pt-3"><strong className="text-sm text-white">{finding.title}</strong><p className="mt-1 text-sm text-slate-400">{finding.description}</p><p className="mt-1 text-sm text-cyan-200">{finding.suggestion}</p></div>)}</div></div>}
        </div>
      );
    }

    return (
      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <input value={filename} onChange={(e) => setFilename(e.target.value)} className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="filename.py" />
            <select value={language} onChange={(e) => setLanguage(e.target.value)} className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100">
              {languages.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800">
            <Editor
              height="520px"
              language={language}
              value={code}
              onChange={(value) => setCode(value ?? '')}
              theme="vs-dark"
              options={{ readOnly: false, minimap: { enabled: false }, fontSize: 14, padding: { top: 16 }, automaticLayout: true }}
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button onClick={() => { setCode(examples[language]); setFilename(`review.${languages.find((item) => item.id === language)?.extension ?? 'txt'}`); setReview(null); }} className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100">Load bad example</button>
            <button onClick={() => { setCode(''); setReview(null); setError(''); }} className="rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100">Clear code</button>
            <button onClick={() => void runReview()} disabled={loading} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60">{loading ? 'Reviewing...' : 'Review Code'}</button>
          </div>

          {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</div>}
          {apiError && <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">Backend connection: {apiError}</div>}
          {actionMessage && <div className="rounded-xl border border-cyan-900 bg-cyan-950/40 px-3 py-2 text-sm text-cyan-100">{actionMessage}</div>}
          {demoResults && <div className="space-y-3 rounded-xl border border-emerald-900 bg-emerald-950/20 p-4">
            <p className="text-xs font-semibold uppercase text-cyan-200">Team rule loaded: {defaultRule}</p>
            <div><div className="text-xs font-bold uppercase text-amber-300">FIRST REVIEW</div><div className="text-sm font-semibold text-white">BEFORE MEMORY</div><p className="mt-1 text-sm text-slate-300">{demoResults.first.summary}</p><p className="mt-1 text-xs text-slate-400">Detected: {demoResults.first.findings.find((finding) => finding.category === 'architecture')?.title || 'No architecture finding returned'}</p><p className="mt-1 text-xs text-emerald-300">Accepted feedback stored in team memory</p></div>
            <div className="border-t border-emerald-900 pt-3"><div className="text-xs font-bold uppercase text-emerald-300">SECOND REVIEW</div><div className="text-sm font-semibold text-white">AFTER MEMORY</div><p className="mt-1 text-sm text-slate-300">{demoResults.second.summary}</p><p className="mt-2 text-sm text-cyan-200">{demoResults.second.findings.find((finding) => finding.category === 'team_memory')?.description || 'The accepted team decision is now available in review memory.'}</p></div>
          </div>}
        </div>

        <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
          {review ? (
            <>
              <div className="flex items-center justify-between">
                <h3 className="text-xl font-semibold text-white">Review Results</h3>
                <span className={`rounded-full border px-2 py-1 text-sm font-semibold ${scoreTone}`}>{review.score}/100</span>
              </div>

              <div className="rounded-2xl border border-slate-700 bg-slate-950 p-4">
                <p className="text-sm text-slate-300">{review.summary}</p>
              </div>

              {review.memory_used.length > 0 && <div className="rounded-xl border border-cyan-900 bg-cyan-950/30 p-3"><div className="text-xs font-semibold uppercase text-cyan-200">Memory used in this review</div>{review.memory_used.map((item, index) => <p key={`${item.source}-${index}`} className="mt-2 text-sm text-slate-200">{item.rule}</p>)}</div>}

              <div className="space-y-3">
                {review.findings.map((finding) => {
                  const status = actionStatus[`${review.review_id}:${finding.id ?? ''}`];
                  return (
                  <div key={finding.id || finding.title} className="rounded-2xl border border-slate-700 bg-slate-950 p-4">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      {renderBadges(finding.severity)}
                      <span className="text-xs uppercase tracking-[0.12em] text-slate-400">{finding.category}</span>
                    </div>
                    <h4 className="text-lg font-semibold text-white">{finding.title}</h4>
                    <p className="mt-2 text-sm text-slate-300">{finding.description}</p>
                    <p className="mt-2 text-sm text-slate-400"><strong className="text-slate-200">Recommended fix:</strong> {finding.suggestion}</p>
                    {finding.evidence && <p className="mt-2 break-words text-xs text-slate-500"><strong className="text-slate-400">Evidence:</strong> {Array.isArray(finding.evidence) ? finding.evidence.join(', ') : finding.evidence}</p>}
                    {finding.team_rule_id && <p className="mt-2 text-xs text-blue-300">Team rule involved: {finding.team_rule_id}</p>}
                    <div className="mt-4 flex gap-2">
                      <button disabled={!finding.id || status === 'accepted'} onClick={() => void acceptFinding(finding.id)} className="rounded-xl bg-emerald-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{status === 'accepted' ? 'Accepted' : 'Accept Suggestion'}</button>
                      <button disabled={!finding.id || status === 'rejected'} onClick={() => void rejectFinding(finding.id)} className="rounded-xl border border-slate-600 px-3 py-2 text-sm text-slate-100 disabled:opacity-50">{status === 'rejected' ? 'Rejected' : 'Reject'}</button>
                      <button onClick={() => void addFindingRule(finding)} className="rounded-xl border border-slate-600 px-3 py-2 text-sm text-slate-100">Add as Team Rule</button>
                    </div>
                  </div>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-950 p-10 text-center text-slate-400">
              Review output will appear here.
            </div>
          )}
        </div>
      </div>
    );
  })();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-6 px-4 py-6 lg:flex-row">
        <aside className="w-full rounded-2xl border border-slate-800 bg-slate-900/80 p-4 lg:max-w-[260px]">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-sm font-bold">AI</div>
            <div>
              <div className="text-sm text-slate-400">Team Memory</div>
              <div className="font-semibold text-white">Code Review Agent</div>
            </div>
          </div>

          <nav className="space-y-2">
            {['Dashboard', 'Code Review', 'Team Memory', 'Review History', 'Settings'].map((item) => (
              <button
                key={item}
                onClick={() => setSidebar(item)}
                className={`w-full rounded-xl px-3 py-2 text-left text-sm ${sidebar === item ? 'bg-slate-800 text-white' : 'text-slate-300 hover:bg-slate-800/70'}`}
              >
                {item}
              </button>
            ))}
          </nav>

          <div className="mt-8 rounded-2xl border border-slate-700 bg-slate-950/80 p-4">
            <div className="text-xs uppercase tracking-[0.12em] text-slate-500">Demo mode</div>
            {demoMode ? <><p className="mt-2 text-xs leading-5 text-slate-400">Run Demo clears local review and rule data before showing memory in action.</p><div className="mt-3 flex gap-2"><button onClick={() => void resetDemo()} className="flex-1 rounded-lg border border-slate-600 px-2 py-2 text-sm text-slate-100">Reset Demo</button><button onClick={() => void demoFlow()} disabled={demoRunning} className="flex-1 rounded-lg bg-emerald-700 px-2 py-2 text-sm font-medium text-white disabled:opacity-50">{demoRunning ? 'Running...' : 'Run Demo'}</button></div></> : <p className="mt-2 text-xs text-slate-400">Demo controls are disabled in Settings.</p>}
          </div>
        </aside>

        <main className="flex-1 space-y-6">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-800 pb-4"><div><p className="text-xs font-semibold uppercase text-cyan-300">Team Memory</p><h1 className="mt-1 text-2xl font-semibold text-white">{sidebar}</h1></div><div className="text-xs text-slate-400">{apiError ? 'Backend disconnected' : 'Backend connected'}{!apiError && <span className="ml-2 inline-block h-2 w-2 rounded-full bg-emerald-400" />}</div></div>
          {content}
        </main>
      </div>
    </div>
  );
}

export default App;
