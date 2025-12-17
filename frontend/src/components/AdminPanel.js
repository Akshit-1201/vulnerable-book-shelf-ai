import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import { Link } from "react-router-dom";

export default function AdminPanel() {
  const [tab, setTab] = useState("books");

  // Vector DB Books state (from MCP)
  const [vectorBooks, setVectorBooks] = useState([]);
  const [loadingBooks, setLoadingBooks] = useState(false);

  // Upload state
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadAuthor, setUploadAuthor] = useState("");
  const [uploadGenre, setUploadGenre] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);
  const uploadPollRef = useRef(null);
  const fileInputRef = useRef(null);

  // Users state
  const [users, setUsers] = useState([]);
  const [uName, setUName] = useState("");
  const [uEmail, setUEmail] = useState("");
  const [uPassword, setUPassword] = useState("");
  const [uPhone, setUPhone] = useState("");
  const [uRole, setURole] = useState("user");
  const [loading, setLoading] = useState(false);

  const API_ROOT = "http://127.0.0.1:8000";
  const MCP_BASE = API_ROOT.replace("8000", "8001");

  // Fetch books from Vector Database (MCP)
  const fetchVectorBooks = async (signal) => {
    setLoadingBooks(true);
    try {
      const res = await axios.get(`${MCP_BASE}/mcp/list_books`, { signal });
      const books = res.data?.books || [];
      setVectorBooks(books);
    } catch (err) {
      if (axios.isCancel(err) || err.name === "CanceledError") return;
      console.error("Could not fetch vector books:", err);
      alert("Could not fetch books from vector database: " + (err?.response?.data?.error || err.message));
    } finally {
      setLoadingBooks(false);
    }
  };

  // Fetch users
  const fetchUsers = async (signal) => {
    try {
      const res = await axios.get(`${API_ROOT}/admin/users`, { signal });
      setUsers(res.data.users || []);
    } catch (err) {
      if (axios.isCancel(err) || err.name === "CanceledError") return;
      console.error("Could not fetch users:", err);
      alert("Could not fetch users: " + (err?.response?.data?.error || err.message));
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    fetchVectorBooks(controller.signal);
    fetchUsers(controller.signal);

    return () => {
      controller.abort();
      if (uploadPollRef.current) {
        clearInterval(uploadPollRef.current);
        uploadPollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Upload status polling
  const getStatusForUpload = async (upload_id) => {
    if (!upload_id) return null;
    try {
      const res = await axios.get(`${API_ROOT}/ingest/status/${upload_id}`);
      return res.data;
    } catch (err) {
      try {
        const res2 = await axios.get(`${MCP_BASE}/mcp/status/${upload_id}`);
        return res2.data;
      } catch (err2) {
        return null;
      }
    }
  };

  const startUploadPolling = (upload_id) => {
    setUploadStatus({ upload_id, status: "indexing", message: "Indexing started" });

    let tries = 0;
    if (uploadPollRef.current) clearInterval(uploadPollRef.current);

    uploadPollRef.current = setInterval(async () => {
      tries++;
      const s = await getStatusForUpload(upload_id);
      if (s && s.status) {
        let statusVal = s.status;
        if (statusVal === "done") statusVal = "completed";
        if (statusVal === "indexed") statusVal = "completed";

        setUploadStatus(prev => ({ 
          ...(prev || {}), 
          upload_id, 
          status: statusVal, 
          message: s.error || s.message || "" 
        }));

        if (["completed", "failed", "error"].includes(statusVal)) {
          clearInterval(uploadPollRef.current);
          uploadPollRef.current = null;
          // Refresh books list after successful upload
          if (statusVal === "completed") {
            fetchVectorBooks();
          }
        }
      }
      if (tries > 40) {
        clearInterval(uploadPollRef.current);
        uploadPollRef.current = null;
        setUploadStatus(prev => ({ 
          ...(prev || {}), 
          status: "timeout", 
          message: "Indexing timed out" 
        }));
      }
    }, 3000);
  };

  // UPLOAD PDF handler
  const handleUploadPdf = async (e) => {
    e.preventDefault();

    if (!uploadTitle.trim() || !uploadAuthor.trim() || !uploadGenre.trim()) {
      alert("Title, Author, and Genre are required for PDF uploads.");
      return;
    }

    if (!uploadFile) {
      alert("Please pick a PDF file to upload.");
      return;
    }

    const user_id = localStorage.getItem("user_id");
    const role = localStorage.getItem("role");
    if (!user_id || role !== "admin") {
      alert("No user id found or you are not an admin. Make sure you're logged in as an admin.");
      return;
    }

    setUploading(true);
    setUploadStatus(null);
    try {
      const form = new FormData();
      form.append("user_id", user_id);
      form.append("pdf", uploadFile, uploadFile.name);
      form.append("title", uploadTitle.trim());
      form.append("author", uploadAuthor.trim());
      form.append("genre", uploadGenre.trim());
      
      // Create book_id slug
      const bookId = uploadTitle.trim().toLowerCase().replace(/\s+/g, "-");
      form.append("book_id", bookId);

      const res = await axios.post(`${API_ROOT}/ingest`, form, { timeout: 120000 });
      const data = res.data || {};

      if (data.error) {
        alert("Upload failed: " + data.error);
      } else {
        alert("Upload started successfully! The book will appear once indexing is complete.");
      }

      if (data.upload_id) {
        startUploadPolling(data.upload_id);
      } else {
        fetchVectorBooks();
      }

      // Clear form
      setUploadFile(null);
      setUploadTitle("");
      setUploadAuthor("");
      setUploadGenre("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      alert("Upload failed: " + (err?.response?.data?.error || err.message));
    } finally {
      setUploading(false);
    }
  };

  // DELETE BOOK from Vector DB
  const handleDeleteVectorBook = async (book) => {
    if (!window.confirm(`Delete "${book.title}" by ${book.author} from the vector database?`)) {
      return;
    }

    setLoadingBooks(true);
    try {
      await axios.post(`${MCP_BASE}/mcp/delete_book`, { book_id: book.book_id });
      alert(`Successfully deleted "${book.title}" from vector database.`);
      fetchVectorBooks();
    } catch (err) {
      alert("Delete failed: " + (err?.response?.data?.error || err.message));
    } finally {
      setLoadingBooks(false);
    }
  };

  // USERS handlers
  const handleAddUser = async (e) => {
    e.preventDefault();
    if (!uName.trim() || !uEmail.trim() || !uPassword.trim()) {
      alert("Username, Email and Password are required");
      return;
    }
    setLoading(true);
    try {
      await axios.post(`${API_ROOT}/admin/add_user`, {
        username: uName.trim(),
        email: uEmail.trim(),
        password: uPassword,
        phone: uPhone.trim(),
        role: uRole
      });
      alert("User added");
      setUName("");
      setUEmail("");
      setUPassword("");
      setUPhone("");
      setURole("user");
      fetchUsers();
    } catch (err) {
      alert("Add user failed: " + (err?.response?.data?.error || err.message));
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
      alert("Delete failed: " + (err?.response?.data?.error || err.message));
    } finally {
      setLoading(false);
    }
  };

  const isUploadDisabled = () => {
    return uploading || !uploadFile || !uploadTitle.trim() || !uploadAuthor.trim() || !uploadGenre.trim();
  };

  return (
    <div className="pt-28 px-4 min-h-screen bg-gray-100">
      <div className="max-w-6xl mx-auto">
        <h2 className="text-3xl font-bold mb-6">Admin Panel</h2>

        {/* Tab Navigation */}
        <div className="mb-6">
          <button
            className={`px-6 py-2 mr-2 rounded-lg font-semibold ${
              tab === "books" 
                ? "bg-indigo-600 text-white shadow-md" 
                : "bg-white text-gray-700 border border-gray-300 hover:bg-gray-50"
            }`}
            onClick={() => setTab("books")}
          >
            📚 Books
          </button>
          <button
            className={`px-6 py-2 rounded-lg font-semibold ${
              tab === "users" 
                ? "bg-indigo-600 text-white shadow-md" 
                : "bg-white text-gray-700 border border-gray-300 hover:bg-gray-50"
            }`}
            onClick={() => setTab("users")}
          >
            👥 Users
          </button>
        </div>

        {/* BOOKS TAB */}
        {tab === "books" && (
          <div className="space-y-6">
            {/* Upload PDF Section */}
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="text-xl font-semibold mb-4 flex items-center">
                <span className="mr-2">📤</span>
                Upload Book PDF
              </h3>
              <form onSubmit={handleUploadPdf} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <input
                    type="text"
                    placeholder="Title *"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <input
                    type="text"
                    placeholder="Author *"
                    value={uploadAuthor}
                    onChange={(e) => setUploadAuthor(e.target.value)}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                  <input
                    type="text"
                    placeholder="Genre *"
                    value={uploadGenre}
                    onChange={(e) => setUploadGenre(e.target.value)}
                    className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>
                <div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="application/pdf"
                    onChange={(e) => setUploadFile(e.target.files && e.target.files[0])}
                    className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
                  />
                </div>
                <div className="flex items-center space-x-4">
                  <button
                    disabled={isUploadDisabled()}
                    className="bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white px-6 py-2 rounded-lg font-semibold transition-colors"
                  >
                    {uploading ? "Uploading..." : "Upload PDF"}
                  </button>
                  <span className="text-sm text-gray-600">
                    All fields are required. Book will be indexed into vector database.
                  </span>
                </div>
              </form>

              {/* Upload status box */}
              {uploadStatus && (
                <div className="mt-4 p-4 border-l-4 rounded-lg bg-gray-50 border-gray-400">
                  <div className="text-sm font-mono text-gray-700">
                    Upload ID: <span className="font-bold">{uploadStatus.upload_id}</span>
                  </div>
                  <div className="mt-2 flex items-center space-x-2">
                    <strong>Status:</strong>
                    <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                      uploadStatus.status === "completed" 
                        ? "bg-green-100 text-green-700" 
                        : uploadStatus.status === "failed" || uploadStatus.status === "error" 
                        ? "bg-red-100 text-red-700" 
                        : "bg-yellow-100 text-yellow-700"
                    }`}>
                      {uploadStatus.status}
                    </span>
                  </div>
                  {uploadStatus.message && (
                    <div className="text-sm text-gray-600 mt-2">{uploadStatus.message}</div>
                  )}
                </div>
              )}
            </div>

            {/* Books List Section */}
            <div className="bg-white p-6 rounded-lg shadow-md">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-xl font-semibold flex items-center">
                  <span className="mr-2">📚</span>
                  Books in the Database
                </h3>
                <button
                  onClick={() => fetchVectorBooks()}
                  className="text-indigo-600 hover:text-indigo-800 text-sm font-semibold"
                >
                  🔄 Refresh
                </button>
              </div>

              {loadingBooks ? (
                <div className="flex items-center justify-center py-8">
                  <div className="h-8 w-8 rounded-full border-4 border-gray-300 border-t-indigo-600 animate-spin"></div>
                  <span className="ml-3 text-gray-600">Loading books...</span>
                </div>
              ) : vectorBooks.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <p className="text-lg">📭 No books uploaded yet.</p>
                  <p className="text-sm mt-2">Upload a PDF above to get started!</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {vectorBooks.map((book) => (
                    <div
                      key={book.book_id}
                      className="flex justify-between items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      <div className="flex-1">
                        <div className="font-bold text-lg text-gray-900">{book.title}</div>
                        <div className="text-sm text-gray-600 mt-1">
                          <span className="font-semibold">Author:</span> {book.author}
                          {book.genre && (
                            <>
                              <span className="mx-2">•</span>
                              <span className="font-semibold">Genre:</span> {book.genre}
                            </>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          {book.vector_count || 0} chunks indexed
                          {book.filename && ` • ${book.filename}`}
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteVectorBook(book)}
                        className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg font-semibold transition-colors ml-4"
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* USERS TAB */}
        {tab === "users" && (
          <div className="bg-white p-6 rounded-lg shadow-md">
            <h3 className="text-xl font-semibold mb-4 flex items-center">
              <span className="mr-2"></span>
              Add New User
            </h3>

            <form onSubmit={handleAddUser} className="mb-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <input
                  value={uName}
                  onChange={(e) => setUName(e.target.value)}
                  placeholder="Username"
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                />
                <input
                  value={uEmail}
                  onChange={(e) => setUEmail(e.target.value)}
                  placeholder="Email"
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                />
                <input
                  value={uPassword}
                  onChange={(e) => setUPassword(e.target.value)}
                  placeholder="Password"
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <input
                  value={uPhone}
                  onChange={(e) => setUPhone(e.target.value)}
                  placeholder="Phone"
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                />
                <select
                  value={uRole}
                  onChange={(e) => setURole(e.target.value)}
                  className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="user">User</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  disabled={loading}
                  className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg font-semibold"
                >
                  {loading ? "Working..." : "Add User"}
                </button>
              </div>
            </form>

            <hr className="my-6" />

            <h4 className="text-lg font-semibold mb-3 flex items-center">
              <span className="mr-2">👥</span>
              All Users
            </h4>
            <div className="space-y-3">
              {users.map((u) => (
                <div
                  key={u.id}
                  className="flex justify-between items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50"
                >
                  <div>
                    <div className="font-bold text-lg">
                      {u.username}{" "}
                      <span className={`text-sm px-2 py-1 rounded-full ${
                        u.role === "admin" 
                          ? "bg-purple-100 text-purple-700" 
                          : "bg-blue-100 text-blue-700"
                      }`}>
                        {u.role}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 mt-1">
                      {u.email} • {u.phone_number || "No phone"}
                    </div>
                  </div>
                  <div className="space-x-2">
                    <Link
                      to={`/admin/users/${u.id}/edit`}
                      className="bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 rounded-lg font-semibold inline-block"
                    >
                      Edit
                    </Link>
                    <button
                      onClick={() => handleDeleteUser(u.id)}
                      className="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-lg font-semibold"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
              {users.length === 0 && (
                <div className="text-center py-8 text-gray-500">No users found.</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}