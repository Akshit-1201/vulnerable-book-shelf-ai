// frontend/src/components/EditUser.js
import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";

export default function EditUser() {
    const { id } = useParams();
    const navigate = useNavigate();

    const [form, setForm] = useState({
        username: "",
        email: "",
        password: "",
        phone: "",
        role: "user"
    });
    const [loading, setLoading] = useState(false);

    const API_ROOT = "http://127.0.0.1:8000";

    // Load current user data
    useEffect(() => {
        const fetchUser = async () => {
            try {
                const res = await axios.get(`${API_ROOT}/admin/users`);
                const user = (res.data.users || []).find((u) => u.id === parseInt(id));
                if (user) {
                    setForm({
                        username: user.username,
                        email: user.email,
                        password: user.password, // yes, plain text (vulnerable demo)
                        phone: user.phone || "",
                        role: user.role || "user"
                    });
                } else {
                    alert("User not found");
                    navigate("/admin");
                }
            } catch (err) {
                alert("Failed to fetch user: " + (err.response?.data?.error || err.message));
                navigate("/admin");
            }
        };
        fetchUser();
    }, [id, navigate]);

    const handleChange = (e) => {
        setForm({ ...form, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            await axios.put(`${API_ROOT}/admin/edit_user/${id}`, form);
            alert("User updated successfully");
            navigate("/admin"); // go back to admin panel
        } catch (err) {
            alert("Update failed: " + (err.response?.data?.error || err.message));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="pt-28 px-4 min-h-screen bg-gray-100">
            <div className="max-w-xl mx-auto bg-white p-6 rounded shadow">
                <h2 className="text-2xl font-bold mb-6">Edit User</h2>
                <form onSubmit={handleSubmit} className="space-y-4">
                    <input
                        name="username"
                        value={form.username}
                        onChange={handleChange}
                        placeholder="Username"
                        className="w-full px-3 py-2 border rounded"
                    />
                    <input
                        name="email"
                        type="email"
                        value={form.email}
                        onChange={handleChange}
                        placeholder="Email"
                        className="w-full px-3 py-2 border rounded"
                    />
                    <input
                        name="password"
                        type="text"
                        value={form.password}
                        onChange={handleChange}
                        placeholder="Password"
                        className="w-full px-3 py-2 border rounded"
                    />
                    <input
                        name="phone"
                        value={form.phone}
                        onChange={handleChange}
                        placeholder="Phone"
                        className="w-full px-3 py-2 border rounded"
                    />
                    <select
                        name="role"
                        value={form.role}
                        onChange={handleChange}
                        className="w-full px-3 py-2 border rounded"
                    >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                    </select>
                    <button
                        type="submit"
                        disabled={loading}
                        className="bg-indigo-600 text-white px-4 py-2 rounded"
                    >
                        {loading ? "Updating..." : "Update User"}
                    </button>
                </form>
            </div>
        </div>
    );
}
