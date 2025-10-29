// frontend/src/components/Search.js
import React, { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

export default function Search() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [contextSnippets, setContextSnippets] = useState([]); // optional supporting snippets
  const [sources, setSources] = useState([]); // optional source list / metadata
  const [loading, setLoading] = useState(false);

  // Base API - keep in sync with other frontend components or move to REACT_APP_API_ROOT
  const API_ROOT = "http://127.0.0.1:8000";
  // MCP often runs on 8001 locally
  const MCP_BASE = API_ROOT.replace("8000", "8001");

  const isListIntent = (q) => {
    if (!q) return false;
    const lower = q.trim().toLowerCase();
    // simple but flexible heuristics
    const listPhrases = [
      "list all",
      "list books",
      "list the books",
      "show all books",
      "all books",
      "what books",
      "give me all books"
    ];
    return listPhrases.some(p => lower.includes(p));
  };

  const parseMcpAnswer = (resData) => {
    // resilient extraction for different response shapes
    if (!resData) return { text: "", snippets: [], sources: [] };

    // Typical RAG responses might include: { answer, text, data, results, context, sources }
    const text =
      (typeof resData.answer === "string" && resData.answer) ||
      (typeof resData.text === "string" && resData.text) ||
      (resData.data && typeof resData.data === "string" && resData.data) ||
      "";

    // context snippets: could be resData.context or resData.results[*].snippet
    let snippets = [];
    if (Array.isArray(resData.context)) {
      snippets = resData.context.slice(0, 6).map(c => (typeof c === "string" ? c : JSON.stringify(c)));
    } else if (Array.isArray(resData.results)) {
      for (const r of resData.results.slice(0, 6)) {
        if (r && (r.snippet || r.text || r.content)) {
          snippets.push(r.snippet || r.text || r.content);
        } else {
          snippets.push(JSON.stringify(r));
        }
      }
    } else if (resData.context && typeof resData.context === "string") {
      snippets = [resData.context];
    }

    // sources: try to extract helpful metadata (title, id, score)
    let srcs = [];
    if (Array.isArray(resData.sources)) {
      srcs = resData.sources.map(s => (typeof s === "string" ? s : JSON.stringify(s)));
    } else if (Array.isArray(resData.results)) {
      srcs = resData.results.slice(0, 6).map(r => {
        if (!r) return "";
        if (r.title) return `${r.title}${r.id ? ` (${r.id})` : ""}`;
        if (r.metadata && r.metadata.title) return r.metadata.title;
        return r.id || r.source || JSON.stringify(r).slice(0, 80);
      });
    }

    return { text: text || "", snippets, sources: srcs };
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setAnswer("");
    setContextSnippets([]);
    setSources([]);

    try {
      const cleaned = query.trim();
      if (!cleaned) {
        alert("Please enter a question or query.");
        setLoading(false);
        return;
      }

      // LIST intent: call MCP list_books
      if (isListIntent(cleaned)) {
        const res = await axios.get(`${MCP_BASE}/mcp/list_books`);
        const books = res.data?.books || res.data || [];
        if (!Array.isArray(books)) {
          setAnswer("No books found (unexpected response shape).");
        } else if (books.length === 0) {
          setAnswer("No books available in the library.");
        } else {
          const lines = books.map(b => `**${b.title || b.name || "Untitled"}** by ${b.author || "Unknown"} (${b.vector_count || b.chunk_count || 0} chunks)`);
          setAnswer("Here are all the books in your database:\n\n" + lines.join("\n\n"));
        }
        setLoading(false);
        return;
      }

      // Otherwise: RAG search
      // Accept shaped response and robustly parse it
      const payload = { query: cleaned, top_k: 6 };
      const res = await axios.post(`${MCP_BASE}/mcp/search`, payload, { timeout: 120000 });

      // parse response for main answer + optional context
      const { text, snippets, sources: srcs } = parseMcpAnswer(res.data || {});
      // fallback: sometimes answer is available at res.data.answer.answer or res.data.payload
      let finalText = text;
      if (!finalText) {
        // try some nested common shapes
        if (res.data?.payload?.answer) finalText = res.data.payload.answer;
        else if (res.data?.response?.answer) finalText = res.data.response.answer;
        else finalText = JSON.stringify(res.data).slice(0, 400);
      }

      setAnswer(finalText);
      setContextSnippets(snippets || []);
      setSources(srcs || []);
    } catch (err) {
      // show helpful diagnostics but avoid huge raw dumps
      const msg = err?.response?.data?.error || err?.response?.data || err.message || String(err);
      alert("Search failed: " + (typeof msg === "string" ? msg : JSON.stringify(msg).slice(0, 300)));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pt-28 flex flex-col items-center min-h-screen bg-gray-100 px-4">
      <h2 className="text-4xl font-bold mb-8">🔎 BookShelf-AI Search</h2>

      {/* Search Bar */}
      <form onSubmit={handleSearch} className="flex space-x-2 w-full max-w-2xl">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask AI about books..."
          className="flex-1 text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-500 disabled:opacity-60"
          required
          disabled={loading}
        />
        <button
          className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 text-lg rounded-lg font-semibold disabled:opacity-60 disabled:cursor-not-allowed"
          disabled={loading}
        >
          {loading ? "Thinking…" : "Search"}
        </button>
      </form>

      {/* Thinking state */}
      {loading && (
        <div className="mt-8 bg-white shadow-lg p-6 rounded-lg w-full max-w-2xl flex items-center space-x-3">
          <div className="h-6 w-6 rounded-full border-4 border-gray-300 border-t-blue-600 animate-spin" />
          <div className="text-lg text-gray-700">Generating answer…</div>
        </div>
      )}

      {/* AI Answer */}
      {!loading && answer && (
        <div className="mt-8 bg-white shadow-lg p-6 rounded-lg w-full max-w-2xl">
          <h4 className="text-xl font-semibold mb-3">🤖 AI Answer</h4>
          <div className="prose text-lg text-gray-800">
            <ReactMarkdown>{answer}</ReactMarkdown>
          </div>

          {/* Context / supporting snippets */}
          {contextSnippets && contextSnippets.length > 0 && (
            <div className="mt-4">
              <h5 className="font-medium mb-2">Supporting snippets</h5>
              <ul className="list-disc list-inside text-sm text-gray-700">
                {contextSnippets.map((s, i) => (
                  <li key={i} className="mb-1">
                    <ReactMarkdown>{s}</ReactMarkdown>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Sources */}
          {sources && sources.length > 0 && (
            <div className="mt-4 text-sm text-gray-600">
              <strong>Sources:</strong>
              <ul className="list-inside list-disc">
                {sources.map((s, i) => (
                  <li key={i} className="truncate max-w-full">{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
