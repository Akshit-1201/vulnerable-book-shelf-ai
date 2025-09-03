import React, { useState } from "react";
import axios from "axios";
import ReactMarkdown from "react-markdown";

export default function Search() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [sql, setSql] = useState("");
  const [answer, setAnswer] = useState("");

  const handleSearch = async () => {
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
    <div style={{ maxWidth: "700px", margin: "0 auto" }}>
      <h3>📚 Book Shelf AI</h3>
      <input
        placeholder="Ask AI about books..."
        style={{ width: "400px", padding: "8px", marginRight: "10px" }}
        onChange={(e) => setQuery(e.target.value)}
      />
      <button onClick={handleSearch}>Search</button>

      {sql && (
        <p style={{ fontSize: "14px", color: "#666" }}>
          <strong>Generated SQL:</strong> {sql}
        </p>
      )}

      {/* {results.length > 0 && (
        <div>
          <h4>📊 Raw Results</h4>
          <pre>{JSON.stringify(results, null, 2)}</pre>
        </div>
      )} */}

      {answer && (
        <div
          style={{
            marginTop: "20px",
            padding: "15px",
            border: "1px solid #ddd",
            borderRadius: "8px",
            backgroundColor: "#f4f8ff"
          }}
        >
          <h4>🤖 AI Answer</h4>
          <ReactMarkdown>{answer}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
