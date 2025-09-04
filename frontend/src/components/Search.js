import React, { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

export default function Search() {
  const [query, setQuery] = useState("");
  const [sql, setSql] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setSql("");
    setAnswer("");

    try {
      const res = await axios.post("http://127.0.0.1:8000/search", { query });
      setSql(res.data.generated_sql || "");
      setAnswer(res.data.answer || "");
    } catch (err) {
      alert("Search failed: " + (err.response?.data?.error || err.message));
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

      {/* Generated SQL */}
      {!loading && sql && (
        <p className="mt-6 text-lg text-gray-700 w-full max-w-2xl">
          <strong>Generated SQL:</strong> {sql}
        </p>
      )}

      {/* AI Answer */}
      {!loading && answer && (
        <div className="mt-8 bg-white shadow-lg p-6 rounded-lg w-full max-w-2xl">
          <h4 className="text-xl font-semibold mb-3">🤖 AI Answer</h4>
          <div className="prose text-lg text-gray-800">
            <ReactMarkdown>{answer}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
