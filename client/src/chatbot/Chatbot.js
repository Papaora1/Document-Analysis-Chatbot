import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import config from '../config'; // Import the config file

function ChatBot() {
    const [query, setQuery] = useState('');
    const [messages, setMessages] = useState([]);
    const [file, setFile] = useState(null);
    const [uploadSuccess, setUploadSuccess] = useState(false);
    const chatBottomRef = useRef(null);

    const handleQueryChange = (event) => {
        setQuery(event.target.value);
    };

    const handleFileChange = (event) => {
        setFile(event.target.files[0]);
    };

    const handleNewMessage = async () => {
        if (query.trim() === '') return;
        try {
            setMessages((prevMessages) => [...prevMessages, { type: 'question', content: query }]);
            setQuery(''); // Clear out the search bar
            const response = await axios.post(`${config.backendUrl}/query`, { question: query });
            setMessages((prevMessages) => [...prevMessages, { type: 'answer', content: response.data.answer }]);
        } catch (error) {
            console.error('Error querying:', error);
        }
    };

    const handleUploadFile = async () => {
        try {
            const formData = new FormData();
            formData.append('file', file);
            await axios.post(`${config.backendUrl}/addDocuments`, formData, {
                headers: {
                    'Content-Type': 'multipart/form-data',
                },
            });
            setUploadSuccess(true);
            setTimeout(() => {
                setUploadSuccess(false);
            }, 3000); // Hide success message after 3 seconds
        } catch (error) {
            console.error('Error uploading file:', error);
        }
    };

    useEffect(() => {
        const handleKeyPress = (event) => {
            if (event.key === 'Enter') {
                handleNewMessage();
            }
        };
        window.addEventListener('keypress', handleKeyPress);
        return () => {
            window.removeEventListener('keypress', handleKeyPress);
        };
    }, []);

    useEffect(() => {
        if (chatBottomRef.current) {
            chatBottomRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages]);

    return (
        <div>
            <h1 style={{ textAlign: 'center' }}>Document Analysis Chatbot</h1>
            <div style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ width: '70%' }}>
                    {messages.map((message, index) => (
                        <div key={index} style={{ display: 'flex', justifyContent: message.type === 'question' ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
                            <div style={{ maxWidth: '50%', backgroundColor: message.type === 'question' ? '#0099FF' : '#e5e6ea', color: message.type === 'question' ? '#ffffff' : '#000000', padding: 10, borderRadius: 10, whiteSpace: 'pre-wrap' }}>
                                {message.content}
                            </div>
                        </div>
                    ))}
                    <textarea
                        value={query}
                        onChange={handleQueryChange}
                        placeholder="Ask me anything..."
                        style={{ width: '100%', height: '100px', marginTop: 10, resize: 'vertical' }}
                    />
                    <button onClick={handleNewMessage} style={{ marginTop: 10 }}>
                        Send
                    </button>
                    <div style={{ marginTop: 20 }}>
                        <input type="file" onChange={handleFileChange} />
                        <button onClick={handleUploadFile} style={{ marginTop: 10 }}>
                            Upload File
                        </button>
                        {uploadSuccess && <span style={{ color: 'green', marginLeft: 10 }}>File uploaded successfully! ✔</span>}
                    </div>
                </div>
                <div ref={chatBottomRef} /> {/* Dummy element to keep buttons fixed at the bottom */}
            </div>
        </div>
    );
}

export default ChatBot;
