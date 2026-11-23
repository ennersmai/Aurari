import React, { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { motion } from 'framer-motion';
import { AlertCircle, ArrowLeft, BrainCircuit, CheckCircle2, GraduationCap, MessageSquare, RefreshCw, Settings, Sparkles, Terminal } from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { cn } from '@/lib/utils';

type Skill = {
  skill_id: string;
  name: string;
  domain?: string;
  mastery_level?: number;
  skill_type?: string;
  definition?: string | Record<string, unknown>;
  execution_config?: unknown;
};

function skillDefinitionToString(def: Skill['definition']): string {
  if (!def) return 'No definition available';
  if (typeof def === 'string') return def;
  if (typeof def === 'object' && def !== null) {
    return (def as any).description || (def as any).name || JSON.stringify(def);
  }
  return 'No definition available';
}

export default function SchoolPage() {
  const router = useRouter();
  const [request, setRequest] = useState('');
  const [skills, setSkills] = useState<Skill[]>([]);
  const [isSynthesizing, setIsSynthesizing] = useState(false);
  const [isLoadingSkills, setIsLoadingSkills] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchSkills = useCallback(async () => {
    setIsLoadingSkills(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE_URL}/learning/skills/registry`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      if (!data.success || !Array.isArray(data.skills)) {
        throw new Error('Invalid skills response format');
      }

      setSkills(data.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load skills');
    } finally {
      setIsLoadingSkills(false);
    }
  }, []);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  const synthesizeSkill = async (event: React.FormEvent) => {
    event.preventDefault();

    const trimmedRequest = request.trim();
    if (!trimmedRequest || isSynthesizing) return;

    setIsSynthesizing(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await fetch(`${API_BASE_URL}/school/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request: trimmedRequest }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}: ${response.statusText}`);
      }

      setSuccess(`Aura learned ${data.tool_name || 'a new skill'}`);
      setRequest('');
      await fetchSkills();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Skill synthesis failed');
    } finally {
      setIsSynthesizing(false);
    }
  };

  return (
    <>
      <Head>
        <title>The Online School | Aura</title>
      </Head>
      <main className="min-h-screen bg-[#050505] text-gray-100 flex flex-col">
        {/* NAV BAR */}
        <nav className="h-10 border-b border-amber-900/30 bg-black/60 flex items-center px-3 gap-1 flex-shrink-0">
          <button onClick={() => router.push('/chat')} className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5">
            <ArrowLeft size={13} /> Back
          </button>
          <button
            onClick={() => router.push('/chat')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
          >
            <MessageSquare size={13} />
            Chat
          </button>
          <button
            onClick={() => router.push('/mission-control')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
          >
            <Settings size={13} />
            Mission Control
          </button>
          <button
            onClick={() => router.push('/school')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-amber-300 bg-amber-900/20 border border-amber-700/30 transition-colors"
          >
            <GraduationCap size={13} />
            School
          </button>
          <button
            onClick={() => router.push('/workbench')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
          >
            <Terminal size={13} />
            Workbench
          </button>

          <div className="flex-1" />

          {/* Branding */}
          <div className="flex items-center gap-2 text-[10px] font-mono text-gray-600">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            <span>AURA</span>
            <span className="text-gray-800">v0.5.0</span>
          </div>
        </nav>
        <div className="mx-auto max-w-6xl space-y-8">
          <header className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-3">
                <BrainCircuit className="h-7 w-7 text-amber-300" />
              </div>
              <div>
                <p className="font-mono text-xs uppercase tracking-[0.35em] text-amber-400/80">Feature 3</p>
                <h1 className="text-3xl font-semibold tracking-tight">The Online School</h1>
              </div>
            </div>
            <p className="max-w-2xl text-sm text-gray-400">
              Ask Aura to synthesize a new executable local skill. The backend validates the generated Python AST before hot-loading it into the learning graph.
            </p>
          </header>

          <section className="rounded-2xl border border-amber-900/40 bg-black/50 p-5 shadow-2xl shadow-amber-950/10">
            <form onSubmit={synthesizeSkill} className="space-y-4">
              <label className="block space-y-2">
                <span className="font-mono text-xs uppercase tracking-[0.2em] text-amber-300">New skill request</span>
                <input
                  value={request}
                  onChange={(event) => setRequest(event.target.value)}
                  placeholder="Learn how to fetch stock prices"
                  disabled={isSynthesizing}
                  className="w-full rounded-xl border border-gray-800 bg-black/70 px-4 py-3 text-sm outline-none transition focus:border-amber-500/70 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </label>
              <button
                type="submit"
                disabled={isSynthesizing || request.trim().length < 3}
                className="inline-flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/15 px-4 py-2 font-mono text-xs uppercase tracking-[0.2em] text-amber-200 transition hover:bg-amber-500/25 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSynthesizing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {isSynthesizing ? 'Aura synthesizing and validating...' : 'Teach Aura'}
              </button>
            </form>

            {error && (
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-red-900/60 bg-red-950/30 p-3 text-sm text-red-300">
                <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {success && (
              <div className="mt-4 flex items-center gap-2 rounded-xl border border-green-900/60 bg-green-950/30 p-3 text-sm text-green-300">
                <CheckCircle2 className="h-4 w-4" />
                <span>{success}</span>
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-gray-800 bg-black/40 p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">Active Skills</h2>
                <p className="font-mono text-xs text-gray-500">{skills.length} skills registered</p>
              </div>
              <button
                onClick={fetchSkills}
                disabled={isLoadingSkills}
                className="rounded-lg border border-gray-800 p-2 text-gray-400 transition hover:border-amber-500/50 hover:text-amber-300 disabled:opacity-50"
                title="Refresh skills"
              >
                <RefreshCw className={cn('h-4 w-4', isLoadingSkills && 'animate-spin')} />
              </button>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {skills.map((skill) => (
                <motion.article
                  key={skill.skill_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-xl border border-gray-800 bg-[#070707] p-4"
                >
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <h3 className="text-sm font-semibold text-gray-100">{skill.name}</h3>
                    <span className="rounded-full border border-amber-900/50 px-2 py-0.5 font-mono text-[10px] uppercase text-amber-300">
                      {skill.skill_type || 'skill'}
                    </span>
                  </div>
                  <p className="mb-3 line-clamp-3 text-xs text-gray-500">{skillDefinitionToString(skill.definition)}</p>
                  <div className="flex items-center justify-between border-t border-gray-900 pt-3 font-mono text-[10px] uppercase tracking-[0.15em] text-gray-600">
                    <span>{skill.domain || 'general'}</span>
                    <span>{Math.round((skill.mastery_level || 0) * 100)}% mastery</span>
                  </div>
                </motion.article>
              ))}
            </div>

            {!isLoadingSkills && skills.length === 0 && (
              <div className="rounded-xl border border-dashed border-gray-800 py-12 text-center text-sm text-gray-500">
                No active skills found.
              </div>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
