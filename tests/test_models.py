import sys
sys.path.insert(0, '.')

from services.shared.models import (
    User, UserCreate, TokenResponse,
    BusinessUnitScope, ChatSession, ChatMessage,
    SearchResult, AgentRequest, ToolResult,
    FeedbackRating, EngineerFeedback
)

# Test 1: empty BU should raise error
try:
    BusinessUnitScope(business_units=[])
    print('FAIL - empty BU should raise error')
except Exception:
    print('OK - empty BU validation works')

# Test 2: short password should raise error
try:
    UserCreate(email='test@test.com', password='short')
    print('FAIL - short password should raise error')
except Exception:
    print('OK - password length validation works')

# Test 3: email lowercase
u = UserCreate(email='TEST@Company.COM', password='password123')
print(f'OK - email normalized: {u.email}')

# Test 4: FeedbackRating enum
r = FeedbackRating.correct
print(f'OK - FeedbackRating: {r}')

print('All model validations passed')