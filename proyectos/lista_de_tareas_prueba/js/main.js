const addTaskButton = document.getElementById('addTaskButton');
const newTaskInput = document.getElementById('newTaskInput');
const taskList = document.getElementById('taskList');

let tasks = [];

function saveTasks() {
    localStorage.setItem('tasks', JSON.stringify(tasks));
}

function renderTasks() {
    taskList.innerHTML = '';

    tasks.forEach(task => {
        const listItem = document.createElement('li');
        listItem.setAttribute('data-id', task.id);
        if (task.completed) {
            listItem.classList.add('completed');
        }

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = task.completed;

        const taskTextSpan = document.createElement('span');
        taskTextSpan.textContent = task.text;

        const deleteButton = document.createElement('button');
        deleteButton.textContent = 'X';
        deleteButton.classList.add('delete-task');

        listItem.appendChild(checkbox);
        listItem.appendChild(taskTextSpan);
        listItem.appendChild(deleteButton);
        taskList.appendChild(listItem);
    });
}

function addTask() {
    const taskText = newTaskInput.value.trim();

    if (taskText === '') {
        return;
    }

    const newTask = {
        id: Date.now(),
        text: taskText,
        completed: false
    };

    tasks.push(newTask);
    newTaskInput.value = '';
    saveTasks();
    renderTasks();
}

function toggleComplete(taskId) {
    tasks = tasks.map(task => 
        task.id == taskId ? { ...task, completed: !task.completed } : task
    );
    saveTasks();
    renderTasks();
}

function deleteTask(taskId) {
    tasks = tasks.filter(task => task.id != taskId);
    saveTasks();
    renderTasks();
}

addTaskButton.addEventListener('click', addTask);

newTaskInput.addEventListener('keypress', (event) => {
    if (event.key === 'Enter') {
        addTask();
    }
});

taskList.addEventListener('click', (event) => {
    const target = event.target;
    const listItem = target.closest('li[data-id]');

    if (!listItem) return;

    const taskId = parseInt(listItem.dataset.id);

    if (target.type === 'checkbox') {
        toggleComplete(taskId);
    } else if (target.classList.contains('delete-task')) {
        deleteTask(taskId);
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const storedTasks = localStorage.getItem('tasks');
    if (storedTasks) {
        tasks = JSON.parse(storedTasks);
    }
    renderTasks();
});