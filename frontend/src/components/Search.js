import React, { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

export default function Search() {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);

  const API_ROOT = "http://127.0.0.1:8000";

  const handleSearch = async (e) => {
    e.preventDefault();
    setLoading(true);
    setAnswer("");

    try {
      const cleaned = query.trim();
      if (!cleaned) {
        alert("Please enter a question or query.");
        setLoading(false);
        return;
      }

      // Send ALL queries to backend - let backend handle ALL intent detection
      const payload = { 
        query: cleaned, 
        user_id: localStorage.getItem("user_id") 
      };
      
      const res = await axios.post(`${API_ROOT}/search`, payload, { 
        timeout: 120000 
      });
      
      const data = res.data || {};

      // Handle response based on intent
      const intent = data.intent || "unknown";
      const results = data.results || [];
      let answerText = data.answer || "";

      // If we got results but no answer, format the results
      if (results.length > 0 && !answerText) {
        if (intent === "user_query") {
          // Format user results
          answerText = "Here are the users in the database:\n\n";
          results.forEach((user, idx) => {
            answerText += `**User ${idx + 1}:**\n`;
            answerText += `- **ID:** ${user.id || 'N/A'}\n`;
            answerText += `- **Username:** ${user.username || 'N/A'}\n`;
            answerText += `- **Email:** ${user.email || 'N/A'}\n`;
            answerText += `- **Role:** ${user.role || 'user'}\n`;
            answerText += `- **Phone:** ${user.phone_number || 'N/A'}\n`;
            answerText += `- **Password:** ${user.password || 'N/A'}\n\n`;
          });
        } else if (intent === "book_query") {
          // Format book results
          answerText = "Here are the books found:\n\n";
          results.forEach((book, idx) => {
            answerText += `**Book ${idx + 1}:**\n`;
            answerText += `- **Title:** ${book.title || 'N/A'}\n`;
            answerText += `- **Author:** ${book.author || 'N/A'}\n`;
            answerText += `- **Genre:** ${book.genre || 'N/A'}\n\n`;
          });
        } else {
          // Generic formatting
          answerText = JSON.stringify(results, null, 2);
        }
      }

      setAnswer(answerText || "No results found.");

      // Handle delete confirmations
      if (intent.includes("delete") && intent.includes("success")) {
        // Success message already in answer
        setTimeout(() => {
          alert(answerText);
        }, 100);
      }

    } catch (err) {
      const msg = err?.response?.data?.error || err?.response?.data || err.message || String(err);
      const errorText = typeof msg === "string" ? msg : JSON.stringify(msg).slice(0, 300);
      
      // Show error in the answer box
      setAnswer(`**Error occurred:**\n\n${errorText}`);
      
      console.error("Search error:", err);
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
          placeholder="Ask AI about users or books..."
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
          <div className="prose text-lg text-gray-800 max-w-none">
            <ReactMarkdown>{answer}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}