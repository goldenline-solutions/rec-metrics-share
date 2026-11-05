import { useState, useRef } from 'react'
import './UploadDropzone.css'

/**
 * UploadDropzone component - handles drag-and-drop and file picker for image uploads
 * 
 * Props:
 * - onFileSelect: function(file) - called when a file is selected
 * - disabled: boolean - whether the dropzone is disabled
 */
function UploadDropzone({ onFileSelect, disabled = false }) {
  const [isDragging, setIsDragging] = useState(false)
  const [preview, setPreview] = useState(null)
  const fileInputRef = useRef(null)

  // Handle file selection (from drag-drop or file picker)
  const handleFile = (file) => {
    if (!file) return
    
    // Validate it's an image
    if (!file.type.startsWith('image/')) {
      alert('Please select an image file')
      return
    }
    
    // Create preview
    const reader = new FileReader()
    reader.onloadend = () => {
      setPreview(reader.result)
    }
    reader.readAsDataURL(file)
    
    // Notify parent
    onFileSelect(file)
  }

  // Drag and drop handlers
  const handleDragOver = (e) => {
    e.preventDefault()
    if (!disabled) {
      setIsDragging(true)
    }
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    
    if (disabled) return
    
    const file = e.dataTransfer.files[0]
    if (file) {
      handleFile(file)
    }
  }

  // File picker handler
  const handleFileInputChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      handleFile(file)
    }
  }

  const handleClick = () => {
    if (!disabled) {
      fileInputRef.current?.click()
    }
  }

  return (
    <div className="upload-dropzone-container">
      <div
        className={`upload-dropzone ${isDragging ? 'dragging' : ''} ${disabled ? 'disabled' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClick}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={handleFileInputChange}
          style={{ display: 'none' }}
          disabled={disabled}
        />
        
        {preview ? (
          <div className="preview-container">
            <img src={preview} alt="Preview" className="preview-image" />
            <p className="preview-text">Click or drag to replace</p>
          </div>
        ) : (
          <div className="dropzone-content">
            <div className="dropzone-icon">📸</div>
            <p className="dropzone-text">
              Drag and drop your screenshot here, or click to select
            </p>
            <p className="dropzone-hint">Supports PNG, JPG, and other image formats</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default UploadDropzone

