-- Migration: Add tutor_name to students
ALTER TABLE students
ADD COLUMN tutor_name VARCHAR(150);
