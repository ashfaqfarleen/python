from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSON
from werkzeug.utils import secure_filename
import pandas as pd
import io

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000"], supports_credentials=True)

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://report_analyzer_owner:npg_Mte6lCJLG0jx@ep-wild-shadow-a8caqys3-pooler.eastus2.azure.neon.tech/report_analyzer?sslmode=require'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Models: Batch and AttendanceRecord ---
class Batch(db.Model):
    __tablename__ = 'batch'
    id = db.Column(db.Integer, primary_key=True)
    year_month = db.Column(db.String, unique=True, nullable=False)
    holidays = db.Column(JSON, nullable=False)
    working_days = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    records = db.relationship('AttendanceRecord', backref='batch', lazy=True)

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_record'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    employee_name = db.Column(db.String, nullable=False)
    project = db.Column(db.String, nullable=True)
    month_total = db.Column(db.Float, nullable=True)
    row_data = db.Column(JSON, nullable=False)

@app.route('/api/save_attendance', methods=['POST'])
def save_attendance():
    """
    Expects JSON:
    {
      "year_month": "May 2025",
      "holidays": [...],
      "working_days": 19,
      "data": [ {...}, {...}, ... ]  # List of attendance rows
    }
    """
    payload = request.get_json()
    year_month = payload.get('year_month')
    holidays = payload.get('holidays')
    working_days = payload.get('working_days')
    data = payload.get('data')

    if not (year_month and holidays is not None and working_days is not None and data):
        return jsonify({'error': 'Missing required fields'}), 400

    # Upsert batch
    batch = Batch.query.filter_by(year_month=year_month).first()
    if not batch:
        batch = Batch(year_month=year_month, holidays=holidays, working_days=working_days)
        db.session.add(batch)
        db.session.commit()
    else:
        batch.holidays = holidays
        batch.working_days = working_days
        db.session.commit()

    # Remove old records for this batch
    AttendanceRecord.query.filter_by(batch_id=batch.id).delete()
    db.session.commit()

    # Insert new records
    for row in data:
        # Normalize keys for row_data
        normalized_row = {}
        for k, v in row.items():
            key = k.replace(" ", "_")
            normalized_row[key] = v
        employee_name = normalized_row.get('EMPLOYEE_NAME')
        project = normalized_row.get('PROJECT')
        month_total = float(normalized_row.get('Month_Total', 0))
        record = AttendanceRecord(
            batch_id=batch.id,
            employee_name=employee_name,
            project=project,
            month_total=month_total,
            row_data=normalized_row
        )
        db.session.add(record)
    db.session.commit()

    return jsonify({'success': True})

@app.route('/api/attendance/employee/<employee_name>', methods=['GET'])
def get_employee_attendance(employee_name):
    records = (
        AttendanceRecord.query
        .join(Batch)
        .filter(AttendanceRecord.employee_name == employee_name)
        .order_by(Batch.year_month)
        .all()
    )
    result = [
        {
            "year_month": record.batch.year_month,
            "holidays": record.batch.holidays,
            "working_days": record.batch.working_days,
            "row_data": record.row_data
        }
        for record in records
    ]
    return jsonify(result)

@app.route('/api/attendance/month/<year_month>', methods=['GET'])
def get_attendance_by_month(year_month):
    """
    Returns all attendance records for a given year_month (e.g., 'May 2025').
    Response:
    {
      "year_month": "May 2025",
      "holidays": [...],
      "working_days": 19,
      "records": [
        {"employee_name": ..., "project": ..., "month_total": ..., "row_data": {...}},
        ...
      ]
    }
    """
    batch = Batch.query.filter_by(year_month=year_month).first()
    if not batch:
        return jsonify({'error': 'No data for this month'}), 404
    records = AttendanceRecord.query.filter_by(batch_id=batch.id).all()
    result = {
        "year_month": batch.year_month,
        "holidays": batch.holidays,
        "working_days": batch.working_days,
        "records": [
            {
                "employee_name": r.employee_name,
                "project": r.project,
                "month_total": r.month_total,
                "row_data": r.row_data
            } for r in records
        ]
    }
    return jsonify(result)

@app.route('/api/upload_attendance_excel', methods=['POST'])
def upload_attendance_excel():
    """
    Accepts an Excel file upload and returns the processed CSV string.
    Expects form-data with:
      - file: the Excel file
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']

    # Read Excel file into DataFrame
    try:
        in_memory = io.BytesIO(file.read())
        df = pd.read_excel(in_memory, sheet_name=0)
    except Exception as e:
        return jsonify({'error': f'Failed to read Excel: {str(e)}'}), 400

    df = df.fillna('')
    df.replace(r'.*HD.*', 0.5, regex=True, inplace=True)
    df.replace(['L'], 0, inplace=True)

    df_csv_string = df.to_csv(index=False)

    return jsonify({
        'df_csv_string': df_csv_string
    })

if __name__ == '__main__':
    print("🚀 Starting Python Attendance Server...")
    print("  • POST /api/save_attendance - Save attendance data")
    print("  • GET  /api/attendance/employee/<employee_name> - Get attendance records for an employee")
    print("  • GET  /api/attendance/month/<year_month> - Get attendance records for a month")
    print("🌐 Server will be available at http://localhost:5001")
    app.run(debug=True, host='127.0.0.1', port=5001)
