import React, { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

export default function Search() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [sql, setSql] = useState("");
  const [answer, setAnswer] = useState("");

  const handleSearch = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post("http://127.0.0.1:8000/search", { query });
      setResults(res.data.results || []);
      setSql(res.data.generated_sql || "");
      setAnswer(res.data.answer || "");
    } catch (err) {
      alert("Search failed: " + (err.response?.data?.error || err.message));
    }
  };

  return (
    <div className="pt-24 flex flex-col items-center min-h-screen bg-gray-100">
      <h2 className="text-3xl font-bold mb-6">🔎 BookShelf-AI Search</h2>
      <form onSubmit={handleSearch} className="flex space-x-2 w-full max-w-lg">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask AI about books..."
          className="flex-1 px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
          required
        />
        <button className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg">
          Search
        </button>
      </form>

      {sql && (
        <p className="mt-4 text-sm text-gray-600">
          <strong>Generated SQL:</strong> {sql}
        </p>
      )}

      {answer && (
        <div className="mt-6 bg-white shadow p-4 rounded-lg w-full max-w-lg">
          <h4 className="font-semibold mb-2">🤖 AI Answer</h4>
          <ReactMarkdown>{answer}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
