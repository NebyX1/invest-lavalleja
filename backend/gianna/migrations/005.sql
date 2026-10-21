DELETE FROM admin_sessions WHERE user_id IN (SELECT id FROM users WHERE mfa_method!='email');
DELETE FROM auth_challenges;
DELETE FROM recovery_codes;
UPDATE users SET mfa_method='email',mfa_enrolled=1,totp_secret=NULL,totp_last_step=-1;
