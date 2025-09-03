import React from 'react';
import Signup from './components/Signup';
import Login from './components/Login';
import Search from './components/Search';



function App() {
  return (
    <div style={{ padding: "20px", fontFamily: "Arial, sans-serif" }}>
      <h1>📚 Book Shelf AI</h1>
      <div style={{ marginBottom: "20px" }}>
        <Signup />
      </div>
      <div style={{ marginBottom: "20px" }}>
        <Login />
      </div>
      <div>
        <Search />
      </div>
    </div>
  );
}

export default App;
