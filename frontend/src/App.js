import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Login from "./components/Login";
import Signup from "./components/Signup";
import Search from "./components/Search";
import AdminPanel from "./components/AdminPanel";
import { useState, useEffect } from "react";
import EditUser from "./components/EditUser";

function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [role, setRole] = useState(null);

  useEffect(() => {
    // hydrate from localStorage
    const storedRole = localStorage.getItem("role");
    const logged = !!localStorage.getItem("isLoggedIn");
    if (logged) {
      setIsLoggedIn(true);
      setRole(storedRole || "user");
    }
  }, []);

  // handleLogin now accepts either a role string or an object { role, user_id }
  const handleLogin = (payload) => {
    let r = "user", uid = null;
    if (typeof payload === "string") {
      r = payload;
    } else if (payload && typeof payload === "object") {
      r = payload.role || "user";
      uid = payload.user_id || null;
    }
    setIsLoggedIn(true);
    setRole(r || "user");
    localStorage.setItem("isLoggedIn", "1");
    localStorage.setItem("role", r || "user");
    if (uid) {
      localStorage.setItem("user_id", String(uid));
    }
  };

  // handleSignup behaves like handleLogin (accepts role or object)
  const handleSignup = (payload) => {
    let r = "user", uid = null;
    if (typeof payload === "string") {
      r = payload;
    } else if (payload && typeof payload === "object") {
      r = payload.role || "user";
      uid = payload.user_id || null;
    }
    setIsLoggedIn(true);
    setRole(r || "user");
    localStorage.setItem("isLoggedIn", "1");
    localStorage.setItem("role", r || "user");
    if (uid) {
      localStorage.setItem("user_id", String(uid));
    }
  };

  const handleLogout = () => {
    setIsLoggedIn(false);
    setRole(null);
    localStorage.removeItem("isLoggedIn");
    localStorage.removeItem("role");
    localStorage.removeItem("user_id");
  };

  return (
    <Router>
      <Navbar isLoggedIn={isLoggedIn} handleLogout={handleLogout} role={role} />
      <Routes>
        <Route path="/" element={<Login onLogin={handleLogin} />} />
        <Route path="/login" element={<Login onLogin={handleLogin} />} />
        <Route path="/signup" element={<Signup onSignup={handleSignup} />} />
        <Route
          path="/search"
          element={isLoggedIn ? <Search role={role} /> : <Login onLogin={handleLogin} />}
        />
        <Route
          path="/admin"
          element={isLoggedIn && role === "admin" ? <AdminPanel /> : <Login onLogin={handleLogin} />}
        />
        <Route
          path="/admin/users/:id/edit"
          element={isLoggedIn && role === "admin" ? <EditUser /> : <Login onLogin={handleLogin} />}
        />
      </Routes>
    </Router>
  );
}

export default App;
