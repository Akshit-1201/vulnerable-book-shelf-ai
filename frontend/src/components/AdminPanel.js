// frontend/src/components/AdminPanel.js
import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Link } from "react-router-dom";

export default function AdminPanel() {
  const [tab, setTab] = useState("books"); // "books" or "users"

  // Books state
  const [books, setBooks] = useState([]);
  const [bTitle, setBTitle] = useState("");
  const [bAuthor, setBAuthor] = useState("");
  const [bGenre, setBGenre] = useState("");

  // Upload state (new)
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadAuthor, setUploadAuthor] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null); // { upload_id, status, message }
  const uploadPollRef = useRef(null);

  // Users state
  const [users, setUsers] = useState([]);
  const [uName, setUName] = useState("");
  const [uEmail, setUEmail] = useState("");
  const [uPassword, setUPassword] = useState("");
  const [uPhone, setUPhone] = useState("");
  const [uRole, setURole] = useState("user");

  const [loading, setLoading] = useState(false);

  const API_ROOT = "http://127.0.0.1:8000";

  // Fetch books
  const fetchBooks = async () => {
    try {
      const res = await axios.get(`${API_ROOT}/books`);
      setBooks(res.data.books || []);
    } catch (err) {
      alert("Could not fetch books: " + (err.response?.data?.error || err.message));
    }
  };

  // Fetch users
  const fetchUsers = async () => {
    try {
      const res = await axios.get(`${API_ROOT}/admin/users`);
      setUsers(res.data.users || []);
    } catch (err) {
      alert("Could not fetch users: " + (err.response?.data?.error || err.message));
    }
  };

  useEffect(() => {
    fetchBooks();
    fetchUsers();
    // cleanup on unmount
    return () => {
      if (uploadPollRef.current) clearInterval(uploadPollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // BOOKS handlers
  const handleAddBook = async (e) => {
    e.preventDefault();
    if (!bTitle || !bAuthor) {
      alert("Title and Author required");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_ROOT}/admin/add_book`, { title: bTitle, author: bAuthor, genre: bGenre });
      alert("Book added");
      setBTitle(""); setBAuthor(""); setBGenre("");
      fetchBooks();
    } catch (err) {
      alert("Add failed: " + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteBook = async (id) => {
    if (!window.confirm("Delete this book?")) return;
    setLoading(true);
    try {
      await axios.delete(`${API_ROOT}/admin/delete_book/${id}`);
      alert("Deleted");
      fetchBooks();
    } catch (err) {
      alert("Delete failed: " + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  // Helper: try to query status endpoints (backend `/ingest/status` first, then MCP `/mcp/status`)
  const getStatusForUpload = async (upload_id) => {
    if (!upload_id) return null;
    try {
      const res = await axios.get(`${API_ROOT}/ingest/status/${upload_id}`);
      return res.data;
    } catch (err) {
      // try fallback to mcp
      try {
        const res2 = await axios.get(`${API_ROOT.replace("8000", "8001")}/mcp/status/${upload_id}`);
        return res2.data;
      } catch (err2) {
        return null;
      }
    }
  };

  const startUploadPolling = (upload_id) => {
    setUploadStatus({ upload_id, status: "indexing", message: "Indexing started" });
    // poll every 3s up to 2 minutes
    let tries = 0;
    if (uploadPollRef.current) clearInterval(uploadPollRef.current);
    uploadPollRef.current = setInterval(async () => {
      tries++;
      const s = await getStatusForUpload(upload_id);
      if (s && s.status) {
        setUploadStatus({ upload_id, status: s.status, message: s.message || "" });
        if (s.status === "published" || s.status === "failed") {
          clearInterval(uploadPollRef.current);
          uploadPollRef.current = null;
          fetchBooks();
        }
      }
      if (tries > 40) { // ~2 minutes
        clearInterval(uploadPollRef.current);
        uploadPollRef.current = null;
        setUploadStatus(prev => ({ ...prev, status: "timeout", message: "Indexing timed out" }));
      }
    }, 3000);
  };

  // UPLOAD handlers (new)
  const handleUploadPdf = async (e) => {
    e.preventDefault();

    // Enforce mandatory title & author for uploads
    if (!uploadTitle || !uploadAuthor) {
      alert("Title and Author are required for PDF uploads.");
      return;
    }

    if (!uploadFile) {
      alert("Please pick a PDF file to upload.");
      return;
    }

    const user_id = localStorage.getItem("user_id");
    if (!user_id) {
      alert("No user id found. Make sure you're logged in as an admin.");
      return;
    }

    setUploading(true);
    setUploadStatus(null);
    try {
      const form = new FormData();
      form.append("user_id", user_id);
      form.append("pdf", uploadFile);
      form.append("title", uploadTitle);
      form.append("author", uploadAuthor);
      // book_id optional - derive from title if provided (simple slug)
      const bookId = (uploadTitle || "").trim().toLowerCase().replace(/\s+/g, "-");
      form.append("book_id", bookId);

      const res = await axios.post(`${API_ROOT}/ingest`, form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000
      });

      // Expecting { upload_id, book_id, status }
      const data = res.data || {};
      alert("Upload response: " + JSON.stringify(data));
      if (data.upload_id) {
        // Start polling status endpoint
        startUploadPolling(data.upload_id);
      } else {
        // If backend returns nothing, attempt to refresh books anyway
        fetchBooks();
      }

      // reset upload form inputs (keep status display)
      setUploadFile(null);
      setUploadTitle("");
      setUploadAuthor("");
      // if input file element exists, clearing state is enough
    } catch (err) {
      alert("Upload failed: " + (err.response?.data?.error || err.message));
    } finally {
      setUploading(false);
    }
  };

  // USERS handlers
  const handleAddUser = async (e) => {
    e.preventDefault();
    if (!uName || !uEmail || !uPassword) {
      alert("Username, Email and Password are required");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_ROOT}/admin/add_user`, {
        username: uName,
        email: uEmail,
        password: uPassword,
        phone: uPhone,
        role: uRole
      });
      alert("User added");
      setUName(""); setUEmail(""); setUPassword(""); setUPhone(""); setURole("user");
      fetchUsers();
    } catch (err) {
      alert("Add user failed: " + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (id) => {
    if (!window.confirm("Delete this user?")) return;
    setLoading(true);
    try {
      await axios.delete(`${API_ROOT}/admin/delete_user/${id}`);
      alert("User deleted");
      fetchUsers();
    } catch (err) {
      alert("Delete failed: " + (err.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  // UI helper to determine whether upload button should be enabled
  const isUploadDisabled = () => {
    return uploading || !uploadFile || !uploadTitle.trim() || !uploadAuthor.trim();
  };

  return (
    <div className="pt-28 px-4 min-h-screen bg-gray-100">
      <div className="max-w-5xl mx-auto">
        <h2 className="text-3xl font-bold mb-4">Admin Panel</h2>

        <div className="mb-6">
          <button
            className={`px-4 py-2 mr-2 rounded ${tab === "books" ? "bg-indigo-600 text-white" : "bg-white border"}`}
            onClick={() => setTab("books")}
          >
            Books
          </button>
          <button
            className={`px-4 py-2 rounded ${tab === "users" ? "bg-indigo-600 text-white" : "bg-white border"}`}
            onClick={() => setTab("users")}
          >
            Users
          </button>
        </div>

        {tab === "books" && (
          <div className="bg-white p-6 rounded shadow mb-8">
            <h3 className="text-xl font-semibold mb-4">Manage Books</h3>
            <form onSubmit={handleAddBook} className="mb-6">
              <div className="flex space-x-3 mb-3">
                <input value={bTitle} onChange={(e) => setBTitle(e.target.value)} placeholder="Title" className="flex-1 px-3 py-2 border rounded" />
                <input value={bAuthor} onChange={(e) => setBAuthor(e.target.value)} placeholder="Author" className="flex-1 px-3 py-2 border rounded" />
                <input value={bGenre} onChange={(e) => setBGenre(e.target.value)} placeholder="Genre" className="flex-1 px-3 py-2 border rounded" />
              </div>
              <div>
                <button disabled={loading} className="bg-indigo-600 text-white px-4 py-2 rounded">
                  {loading ? "Working..." : "Add Book"}
                </button>
              </div>
            </form>

            {/* UPLOAD PDF area (new) */}
            <div className="mb-6 border-t pt-6">
              <h4 className="font-semibold mb-3">Upload Book PDF (admin-only)</h4>
              <form onSubmit={handleUploadPdf} className="space-y-3">
                <div className="flex space-x-3">
                  <input
                    type="text"
                    placeholder="Title *"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    className="flex-1 px-3 py-2 border rounded"
                  />
                  <input
                    type="text"
                    placeholder="Author *"
                    value={uploadAuthor}
                    onChange={(e) => setUploadAuthor(e.target.value)}
                    className="flex-1 px-3 py-2 border rounded"
                  />
                </div>
                <div>
                  <input
                    type="file"
                    accept="application/pdf"
                    onChange={(e) => setUploadFile(e.target.files[0])}
                  />
                </div>
                <div>
                  <button disabled={isUploadDisabled()} className="bg-green-600 disabled:opacity-60 text-white px-4 py-2 rounded">
                    {uploading ? "Uploading..." : "Upload PDF"}
                  </button>
                </div>
                <div className="text-sm text-gray-600">
                  Title and Author are required. Uploads are forwarded to the MCP for indexing (vector DB) — admin-only.
                </div>
              </form>

              {/* Upload status box */}
              {uploadStatus && (
                <div className="mt-3 p-3 border rounded bg-gray-50">
                  <div className="text-sm">Upload id: <span className="font-mono">{uploadStatus.upload_id}</span></div>
                  <div className="mt-1">
                    <strong>Status:</strong>{" "}
                    <span className={
                      uploadStatus.status === "published" ? "text-green-600" :
                      uploadStatus.status === "failed" ? "text-red-600" : "text-yellow-600"
                    }>
                      {uploadStatus.status}
                    </span>
                  </div>
                  {uploadStatus.message && <div className="text-sm text-gray-600 mt-1">{uploadStatus.message}</div>}
                </div>
              )}
            </div>

            <div>
              <h4 className="font-semibold mb-2">Books</h4>
              <ul>
                {books.map(b => (
                  <li key={b.id} className="flex justify-between items-center mb-3">
                    <div>
                      <div className="font-semibold">{b.title}</div>
                      <div className="text-sm text-gray-600">{b.author} — {b.genre} {b.status ? `• ${b.status}` : ""}</div>
                    </div>
                    <div>
                      <button onClick={() => handleDeleteBook(b.id)} className="bg-red-500 text-white px-3 py-1 rounded">Delete</button>
                    </div>
                  </li>
                ))}
                {books.length === 0 && <li className="text-gray-600">No books found.</li>}
              </ul>
            </div>
          </div>
        )}

        {tab === "users" && (
          <div className="bg-white p-6 rounded shadow mb-8">
            <h3 className="text-xl font-semibold mb-4">Manage Users</h3>

            <form onSubmit={handleAddUser} className="mb-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <input value={uName} onChange={(e) => setUName(e.target.value)} placeholder="Username" className="px-3 py-2 border rounded" />
                <input value={uEmail} onChange={(e) => setUEmail(e.target.value)} placeholder="Email" className="px-3 py-2 border rounded" />
                <input value={uPassword} onChange={(e) => setUPassword(e.target.value)} placeholder="Password" className="px-3 py-2 border rounded" />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <input value={uPhone} onChange={(e) => setUPhone(e.target.value)} placeholder="Phone" className="px-3 py-2 border rounded" />
                <select value={uRole} onChange={(e) => setURole(e.target.value)} className="px-3 py-2 border rounded">
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
                <div>
                  <button disabled={loading} className="bg-indigo-600 text-white px-4 py-2 rounded">
                    {loading ? "Working..." : "Add User"}
                  </button>
                </div>
              </div>
            </form>

            <div>
              <h4 className="font-semibold mb-2">Users</h4>
              <ul>
                {users.map(u => (
                  <li key={u.id} className="flex justify-between items-center mb-3">
                    <div>
                      <div className="font-semibold">{u.username} <span className="text-sm text-gray-500">({u.role})</span></div>
                      <div className="text-sm text-gray-600">{u.email} • {u.phone}</div>
                    </div>
                    <div className="space-x-2">
                      <Link to={`/admin/users/${u.id}/edit`} className="bg-yellow-500 text-white px-3 py-1 rounded">Edit</Link>
                      <button onClick={() => handleDeleteUser(u.id)} className="bg-red-500 text-white px-3 py-1 rounded">Delete</button>
                    </div>
                  </li>
                ))}
                {users.length === 0 && <li className="text-gray-600">No users found.</li>}
              </ul>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
