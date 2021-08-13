


## Menu
[delete_from_included_courses](#delete_from_included_courses)

[add role](#add_role)

[delete_role](#delete_role)

[delete_member](#delete_member)


<a name="attach_to_included_courses"></a>
## Attach courses to included courses for a program 
- /api/proxy/discovery/api/v1/programs/[program_uuid]/courses/
- POST
### Input:
    {
        course_ids:[course_id0, course_id1, ...]
    }
### Output:
    {
        results:[course_id0, course_id1, ...]
    }


<a name="delete_from_included_courses"></a>
## Delete included courses from a program 
- /api/proxy/discovery/api/v1/programs/[program_uuid]/courses/
- DELETE
### Input:
    {
        course_ids:[course_id0, course_id1, ...]
    }
### Output:
    {
        results:[course_id0, course_id1, ...]
    }


<a name="resort_included_courses"></a>
## Resort included courses from a program 
- /api/proxy/discovery/api/v1/programs/[program_uuid]/courses/
- PATCH
### Input:
    {
        param:[{course_id:'course_id0', order_no:1}]
    }
### Output:
    {
        results:[course_id0, course_id1, ...]
    }


