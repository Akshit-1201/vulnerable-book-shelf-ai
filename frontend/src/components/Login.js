// frontend/src/components/Login.js
import React, { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post("http://127.0.0.1:8000/login", {
        email,
        password,
      });
      const role = res.data.role || "user";
      alert(res.data.message || "Login successful");
      onLogin(role);
      navigate("/search");
    } catch (err) {
      const errorMsg = err.response?.data?.error || err.message;
      alert("Login failed: " + errorMsg);
    }
  };

  return (
    <div className="flex justify-center items-center h-screen bg-gradient-to-br from-blue-100 to-indigo-200">
      <div className="bg-white shadow-xl rounded-2xl p-8 w-96">
        <h2 className="text-4xl font-bold text-center mb-6">Login</h2>
        <form onSubmit={handleLogin} className="space-y-5">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-400"
            required
          />
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-blue-400"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute inset-y-0 right-3 flex items-center text-gray-500"
            >
              {showPassword ? "👁️‍🗨️" : "👁️"}
            </button>
          </div>
          <button className="w-full bg-blue-600 hover:bg-blue-700 text-white py-3 text-lg rounded-lg font-semibold">
            Login
          </button>
        </form>
        <p className="text-base text-center mt-4">
          Do not have an account?{" "}
          <a href="/signup" className="text-blue-600 hover:underline">
            Signup
          </a>
        </p>
      </div>
    </div>
  );
}
