// frontend/src/components/Signup.js
import React, { useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

export default function Signup({ onSignup }) {
  const [form, setForm] = useState({ username: "", email: "", password: "", phone: "" });
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  const handleSignup = async (e) => {
    e.preventDefault();
    try {
      const res = await axios.post("http://127.0.0.1:8000/signup", form);
      alert(res.data.message || "Signup successful");
      // new users are regular users
      onSignup("user");
      navigate("/search");
    } catch (err) {
      alert("Signup failed: " + (err.response?.data?.error || err.message));
    }
  };

  return (
    <div className="flex justify-center items-center h-screen bg-gradient-to-r from-purple-200 to-indigo-200">
      <div className="bg-white shadow-xl rounded-2xl p-8 w-96">
        <h2 className="text-4xl font-bold text-center mb-6">Create Account</h2>
        <form onSubmit={handleSignup} className="space-y-5">
          <input
            name="username"
            placeholder="Username"
            value={form.username}
            onChange={handleChange}
            className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-indigo-400"
            required
          />
          <input
            type="email"
            name="email"
            placeholder="Email"
            value={form.email}
            onChange={handleChange}
            className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-indigo-400"
            required
          />
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              placeholder="Password"
              value={form.password}
              onChange={handleChange}
              className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-indigo-400"
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
          <input
            name="phone"
            placeholder="Phone"
            value={form.phone}
            onChange={handleChange}
            className="w-full text-lg px-4 py-3 border rounded-lg focus:ring-2 focus:ring-indigo-400"
            required
          />
          <button className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 text-lg rounded-lg font-semibold">
            Signup
          </button>
        </form>
      </div>
    </div>
  );
}
