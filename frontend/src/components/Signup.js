import React, { useState } from "react";
import axios from "axios";

export default function Signup() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phone, setPhone] = useState("");

  const handleSignup = async () => {
    try {
      const res = await axios.post("http://127.0.0.1:8000/signup", {
        username,
        email,
        password,
        phone
      });
      alert(res.data.message || "Signup successful");
    } catch (err) {
      alert("Signup failed: " + err.response?.data?.error || err.message);
    }
  };

  return (
    <div>
      <h3>Signup</h3>
      <input placeholder="Username" onChange={(e) => setUsername(e.target.value)} />
      <input placeholder="Email" onChange={(e) => setEmail(e.target.value)} />
      <input placeholder="Password" type="password" onChange={(e) => setPassword(e.target.value)} />
      <input placeholder="Phone" onChange={(e) => setPhone(e.target.value)} />
      <button onClick={handleSignup}>Signup</button>
    </div>
  );
}
