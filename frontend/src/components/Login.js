import React, { useState } from "react";
import axios from "axios";

export default function Login() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");

    const handleLogin = async () => {
        try {
            const res = await axios.post("http://127.0.0.1:8000/login", {
                email,
                password
            });
            alert(res.data.message || "Login successful");
        } catch (err) {
            //   alert("Login failed: " + err.response?.data?.error || err.message);
            const errorMsg = err.response?.data?.error || err.message;
            alert("Login failed: " + errorMsg);
        }
    };

    return (
        <div>
            <h3>Login</h3>
            <input placeholder="Email" onChange={(e) => setEmail(e.target.value)} />
            <input placeholder="Password" type="password" onChange={(e) => setPassword(e.target.value)} />
            <button onClick={handleLogin}>Login</button>
        </div>
    );
}
